#!/usr/bin/env python3
"""
preprocess.py — insert blank lines before tables/lists that python-markdown's
classic parser would otherwise swallow into the preceding paragraph, and pull
HTML comments out into placeholders so they survive conversion intact.

Why this exists: python-markdown (unlike GFM renderers) will not let a table
or list interrupt a paragraph -- it needs a blank line first. Real-world .md
(hand-written or LLM-authored) frequently omits that blank line, e.g.:

    **Key Inputs:**
    | Input | Source |
    |-------|--------|

Fed straight into the converter, the table lines get swallowed into the
preceding <p> as literal pipe-delimited text. Same failure mode for a list
directly following a bold "label" line with no blank line before it.

Rule (deliberately simple -- do not add "is this an indented continuation"
exceptions, they cause more bugs than they fix): insert a blank line before
any table-row line or list-item line that is immediately preceded by a
non-blank line which is not itself the same construct type.

Fenced code blocks are protected from ALL of the above before any other
pass runs (see protect_code_fences). Two real bugs motivated this, both
found by testing against a PRD containing an example API payload:

1. A fenced block containing `<!-- ... -->` as literal example HTML (not an
   authored PRD comment) was getting extracted by extract_comments() and
   replaced with a raw, never-restored placeholder string that then
   rendered as visible garbage text inside the code sample -- silently
   destroying real content in a way none of the five verify.py checks
   catch (word_diff deliberately strips fenced code from BOTH sides, so it
   can't see the loss).
2. A fenced block containing YAML/JSON with lines starting `- key: value`
   was getting spurious blank lines inserted by insert_blank_lines(),
   because that function has no concept of "inside a fence" -- it just
   pattern-matches list-item-looking lines wherever they occur. This
   changes the rendered code sample's formatting relative to the source.
Both are exactly the "swallowed content, invisible on a skim" failure mode
this whole skill exists to prevent -- they just happen to occur inside
fences instead of tables/lists, which the original design didn't guard.
"""
import re
import sys

TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
LIST_ITEM_RE = re.compile(r"^\s*([-*+]\s|\d+\.\s)")
COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
FENCE_OPEN_RE = re.compile(r"^(\s*)(`{3,}|~{3,})")
FENCE_CLOSE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*$")
CODEBLOCK_PLACEHOLDER = "MDHTML_CODEBLOCK_PLACEHOLDER_{}"


def _is_table_row(line: str) -> bool:
    return bool(TABLE_ROW_RE.match(line))


def _is_list_item(line: str) -> bool:
    return bool(LIST_ITEM_RE.match(line))


def protect_code_fences(md_text: str):
    """Replace every fenced code block (``` or ~~~, any language tag) with a
    single-line placeholder, verbatim block saved for restoration. Must run
    BEFORE extract_comments() and insert_blank_lines() -- both of those
    operate on raw text with no fence awareness, and running them first is
    exactly what caused the two bugs described in the module docstring.

    Deliberately line-based and simple rather than a single DOTALL regex --
    matches the philosophy already established for insert_blank_lines(): a
    dumb, obviously-correct rule beats a clever one that mishandles an edge
    case. Handles multiple blocks, both fence characters, and tolerates an
    unterminated trailing fence (malformed input) by treating the rest of
    the document as one final block rather than silently mis-parsing it.

    Returns (text_with_placeholders, [verbatim_block_strings]).
    """
    lines = md_text.split("\n")
    out_lines = []
    blocks = []
    in_fence = False
    current = []
    for line in lines:
        if not in_fence:
            if FENCE_OPEN_RE.match(line):
                in_fence = True
                current = [line]
            else:
                out_lines.append(line)
        else:
            current.append(line)
            if FENCE_CLOSE_RE.match(line):
                in_fence = False
                blocks.append("\n".join(current))
                out_lines.append(CODEBLOCK_PLACEHOLDER.format(len(blocks) - 1))
                current = []
    if in_fence:  # unterminated fence -- flush rather than lose it
        blocks.append("\n".join(current))
        out_lines.append(CODEBLOCK_PLACEHOLDER.format(len(blocks) - 1))
    return "\n".join(out_lines), blocks


def restore_code_fences(md_text: str, blocks) -> str:
    """Undo protect_code_fences(). Runs last, so the fenced blocks land back
    in the output byte-for-byte identical to the source -- nothing upstream
    of this call ever saw their contents."""
    for idx, block in enumerate(blocks):
        md_text = md_text.replace(CODEBLOCK_PLACEHOLDER.format(idx), block)
    return md_text


def insert_blank_lines(md_text: str) -> str:
    """Walk the source line by line; insert a blank line whenever a table or
    list construct starts right after a non-blank, non-matching line."""
    lines = md_text.split("\n")
    out = []
    for i, line in enumerate(lines):
        if i > 0:
            prev = lines[i - 1]
            prev_blank = prev.strip() == ""
            starts_table = _is_table_row(line) and not _is_table_row(prev)
            starts_list = _is_list_item(line) and not _is_list_item(prev)
            if not prev_blank and (starts_table or starts_list):
                out.append("")
        out.append(line)
    return "\n".join(out)


def extract_comments(md_text: str):
    """Replace <!-- ... --> blocks with a placeholder paragraph so they
    survive markdown conversion untouched (python-markdown otherwise only
    preserves comments reliably as raw HTML blocks, which requires blank
    lines on both sides that hand-authored source often lacks -- and even
    then, comments are invisible in rendered output by default).

    Returns (text_with_placeholders, [comment_bodies])
    """
    comments = []

    def _replace(m):
        comments.append(m.group(1).strip())
        idx = len(comments) - 1
        # Placeholder sits on its own line, blank lines on both sides,
        # so it always becomes its own <p> that we can find and replace
        # after conversion.
        return f"\n\nMDHTML_COMMENT_PLACEHOLDER_{idx}\n\n"

    new_text = COMMENT_RE.sub(_replace, md_text)
    return new_text, comments


def preprocess(md_text: str):
    """Full preprocessing pass. Returns (processed_text, comments).

    Order matters: protect fenced code blocks FIRST so extract_comments()
    and insert_blank_lines() never see their contents, then restore LAST so
    the restored text still carries the placeholder-driven blank-line
    padding those two passes may have added around the block (matching
    prior behavior for the non-fence case) without having mangled anything
    inside it."""
    text, code_blocks = protect_code_fences(md_text)
    text, comments = extract_comments(text)
    text = insert_blank_lines(text)
    text = restore_code_fences(text, code_blocks)
    return text, comments


def main():
    if len(sys.argv) != 3:
        print("usage: preprocess.py <input.md> <output.md>", file=sys.stderr)
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, "r", encoding="utf-8") as f:
        raw = f.read()
    processed, comments = preprocess(raw)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(processed)
    print(f"wrote {dst} ({len(comments)} comment(s) extracted to placeholders)")


if __name__ == "__main__":
    main()
