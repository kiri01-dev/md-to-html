#!/usr/bin/env python3
"""
verify.py -- the mandatory verification gate. Do not consider a conversion
done until this exits 0.

Why this exists: at document length (hundreds of lines, dozens of tables),
visual/spot-check review reliably misses real content loss -- a swallowed
table, a duplicated heading id, a silently dropped HTML comment. None of
these are visible from a quick look at the rendered page. Every check here
was chosen because it caught a real bug in practice, not preemptively:

  1. word_diff            -- catches swallowed/dropped content anywhere
  2. tag_balance           -- catches malformed HTML from the pipeline
  3. id_nav_parity         -- catches the "sidebar links go nowhere" bug
  4. table_list_counts     -- catches tables/lists that flattened to text
  5. stray_markdown        -- catches un-rendered markdown leaking through

A 6th check -- fact-anchored spot checks ("this doc says 'ten deterministic
detections', does the rendered structure actually have ten?") -- is
inherently document-specific and is NOT automated here. The skill should
prompt for any counts/totals the source document asserts about itself and
check those by hand; see SKILL.md.

Usage:
    python verify.py <input.md> <output.html> [--json]

Exits 0 if all checks pass, 1 otherwise. Prints which check(s) failed and
why -- never just "verification failed".
"""
import argparse
import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

# Void elements never need a closing tag.
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


def strip_fenced_code(md_text: str) -> str:
    """Remove ``` and ~~~ fenced code blocks. Shared by every check below
    that reasons about markdown *syntax* in the source, because a code
    sample can legitimately contain pipe characters, list-marker-looking
    lines, or table syntax shown as illustrative text -- none of that is
    real markdown structure and none of it should count toward what the
    rendered structure is expected to contain. (check_table_list_counts
    used to skip this step and treated a code-fenced example table as a
    real table that "flattened," a false failure -- see SKILL.md.)"""
    text = re.sub(r"```.*?```", " ", md_text, flags=re.DOTALL)
    text = re.sub(r"~~~.*?~~~", " ", text, flags=re.DOTALL)
    return text


# ---------------------------------------------------------------------------
# 1. Word diff -- strip markdown syntax from source, strip HTML tags from
#    output, tokenize both, Counter-diff. A near-zero diff (explainable by
#    punctuation-splitting artifacts) is strong evidence of content parity.
# ---------------------------------------------------------------------------
def strip_markdown(md_text: str) -> str:
    text = md_text
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)  # comments (see note in report)
    text = strip_fenced_code(text)  # fenced code blocks
    text = re.sub(r"`([^`]*)`", r"\1", text)  # inline code
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)  # headings
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)  # blockquote markers
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)  # list bullets
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)  # ordered list markers
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links -> text
    # bold/italic. Delimiters must sit at word edges, so snake_case identifiers such as
    # position_state keep their underscores (and tokenize the same way as the rendered text).
    text = re.sub(r"(?<!\w)[*_]{1,3}([^*_\n]+?)[*_]{1,3}(?!\w)", r"\1", text)
    text = re.sub(r"^\s*\|", "", text, flags=re.MULTILINE)
    text = re.sub(r"\|\s*$", "", text, flags=re.MULTILINE)
    text = text.replace("|", " ")  # remaining table pipes
    text = re.sub(r"^\s*\|?[-:\s]+\|[-:\s|]+$", " ", text, flags=re.MULTILINE)  # separator rows
    return text


def strip_html(html_text: str) -> str:
    text = re.sub(r"<style.*?</style>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&mdash;|&ndash;", "-", text)
    text = re.sub(r"&[a-zA-Z#0-9]+;", " ", text)
    return text


def tokenize(text: str):
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


def check_word_diff(md_text: str, html_text: str, tolerance: float = 0.02):
    md_tokens = Counter(tokenize(strip_markdown(md_text)))
    html_tokens = Counter(tokenize(strip_html(html_text)))
    missing = md_tokens - html_tokens  # in source, not in output -> likely dropped content
    added = html_tokens - md_tokens  # in output, not in source -> likely nav duplication etc.
    total_source = sum(md_tokens.values()) or 1
    missing_ratio = sum(missing.values()) / total_source
    passed = missing_ratio <= tolerance
    top_missing = missing.most_common(15)
    return {
        "name": "word_diff",
        "passed": passed,
        "detail": (
            f"{sum(missing.values())} tokens present in source but missing from output "
            f"({missing_ratio:.1%} of {total_source} source tokens; tolerance {tolerance:.0%}). "
            f"Note: nav sidebar duplicates heading text into 'added' tokens by design, "
            f"that's expected and not a failure signal. Top missing tokens: {top_missing}"
        ),
    }


# ---------------------------------------------------------------------------
# 2. HTML well-formedness -- stack-based tag balance check.
# ---------------------------------------------------------------------------
class _BalanceChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass  # self-closed, nothing to push

    def handle_endtag(self, tag):
        if not self.stack:
            self.errors.append(f"orphan closing tag </{tag}> with nothing open")
            return
        if self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            # mismatched nesting -- pop until we find it, flag what we skipped
            skipped = []
            while self.stack and self.stack[-1] != tag:
                skipped.append(self.stack.pop())
            if self.stack:
                self.stack.pop()
            self.errors.append(f"</{tag}> closed out of order, skipped over open: {skipped}")
        else:
            self.errors.append(f"</{tag}> has no matching open tag")


def check_tag_balance(html_text: str):
    checker = _BalanceChecker()
    checker.feed(html_text)
    unclosed = checker.stack
    errors = list(checker.errors)
    if unclosed:
        errors.append(f"{len(unclosed)} tag(s) never closed: {unclosed}")
    return {
        "name": "tag_balance",
        "passed": len(errors) == 0,
        "detail": "; ".join(errors) if errors else "all tags balanced",
    }


# ---------------------------------------------------------------------------
# 3. ID uniqueness + nav/heading parity.
# ---------------------------------------------------------------------------
def check_id_nav_parity(html_text: str):
    all_ids = re.findall(r'\bid="([^"]*)"', html_text)
    id_counts = Counter(all_ids)
    duplicates = [i for i, c in id_counts.items() if c > 1]

    heading_ids = set(re.findall(r'<h[23][^>]*\bid="([^"]*)"', html_text))
    nav_hrefs = set(re.findall(r'class="nav-link[^"]*"[^>]*href="#([^"]*)"', html_text))
    # also catch href-before-class attribute order
    nav_hrefs |= set(re.findall(r'href="#([^"]*)"[^>]*class="nav-link', html_text))

    missing_from_nav = heading_ids - nav_hrefs
    dangling_nav_links = nav_hrefs - heading_ids

    problems = []
    if duplicates:
        problems.append(f"duplicate id attribute(s): {duplicates}")
    if missing_from_nav:
        problems.append(f"heading id(s) with no nav entry: {sorted(missing_from_nav)}")
    if dangling_nav_links:
        problems.append(f"nav link(s) pointing at a non-existent heading id: {sorted(dangling_nav_links)}")

    return {
        "name": "id_nav_parity",
        "passed": len(problems) == 0,
        "detail": "; ".join(problems) if problems else (
            f"{len(all_ids)} ids all unique, {len(heading_ids)} headings <-> "
            f"{len(nav_hrefs)} nav links match exactly"
        ),
    }


# ---------------------------------------------------------------------------
# 4. Table/list count sanity checks -- smoke test, not exact equality.
# ---------------------------------------------------------------------------
def check_table_list_counts(md_text: str, html_text: str):
    # Strip fenced code first -- a doc can legitimately show table/list
    # syntax as a literal example inside a code fence, and that must not
    # count as real markdown structure the renderer was supposed to convert.
    source_text = strip_fenced_code(md_text)

    # Table separator rows like |---|---| or | :--- | ---: |
    sep_rows = len([l for l in source_text.splitlines()
                    if "|" in l and re.match(r"^\s*\|?[\s:|-]*-{3,}[\s:|-]*$", l)])
    html_tables = html_text.count("<table")

    list_lines = len(re.findall(r"^\s*([-*+]\s|\d+\.\s)", source_text, flags=re.MULTILINE))
    html_li = html_text.count("<li")

    problems = []
    if html_tables < sep_rows:
        problems.append(
            f"source has {sep_rows} table-separator row(s) but output has only "
            f"{html_tables} <table> element(s) -- a table likely flattened into a paragraph"
        )
    # list items can legitimately merge/split across nesting, so use a generous
    # tolerance band rather than exact equality -- big drops are the real signal
    if html_li < list_lines * 0.8:
        problems.append(
            f"source has ~{list_lines} list-item line(s) but output has only "
            f"{html_li} <li> element(s) -- a list likely flattened into a paragraph"
        )
    return {
        "name": "table_list_counts",
        "passed": len(problems) == 0,
        "detail": "; ".join(problems) if problems else (
            f"{sep_rows} source table(s) -> {html_tables} rendered; "
            f"~{list_lines} source list line(s) -> {html_li} rendered <li>"
        ),
    }


# ---------------------------------------------------------------------------
# 5. Stray markdown grep -- un-rendered markdown escaped into the output.
# ---------------------------------------------------------------------------
def check_stray_markdown(html_text: str):
    # Only look inside visible body text -- not inside <pre>/<code> where
    # literal markdown-looking characters are expected and correct; not
    # inside headings, where a title that legitimately starts with a number
    # ("1. KYB Verification Family") is not a markdown-list false positive;
    # and not inside the nav sidebar, which duplicates every heading's text
    # as link text for the exact same reason.
    scrubbed = re.sub(r"<pre\b.*?</pre>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    # Inline code keeps a token so "`x` + y" does not read as a "+ y" bullet.
    scrubbed = re.sub(r"<code\b.*?</code>", "CODE", scrubbed, flags=re.DOTALL | re.IGNORECASE)
    scrubbed = re.sub(r"<h[1-6]\b.*?</h[1-6]>", "", scrubbed, flags=re.DOTALL | re.IGNORECASE)
    scrubbed = re.sub(r"<nav\b.*?</nav>", "", scrubbed, flags=re.DOTALL | re.IGNORECASE)
    scrubbed = re.sub(r"<(script|style)\b.*?</\1>", "", scrubbed, flags=re.DOTALL | re.IGNORECASE)
    # Inline tags do not start a new line of text; only block boundaries do.
    scrubbed = re.sub(r"</?(strong|em|b|i|a|span|mark|sup|sub|del|s|u)\b[^>]*>", "", scrubbed, flags=re.IGNORECASE)
    # A table cell that starts with "0. " or "- " is authored text: markdown never renders
    # lists inside cells. Mark cell starts so the line-start marker checks skip them.
    scrubbed = re.sub(r"(<t[dh]\b[^>]*>)", "\\1\u00a6", scrubbed, flags=re.IGNORECASE)
    text_only = re.sub(r"<[^>]+>", "\n", scrubbed)

    hits = []
    for line in text_only.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^[-*+]\s+\S", line):
            hits.append(f"un-rendered bullet marker: {line[:80]!r}")
        elif re.match(r"^\d+\.\s+\S", line) and len(line) < 120:
            hits.append(f"possible un-rendered ordered-list marker: {line[:80]!r}")
        elif re.match(r"^\|.*\|.*\|", line):
            hits.append(f"un-rendered table row: {line[:80]!r}")
        elif re.search(r"\*\*[^*]+\*\*", line):
            hits.append(f"un-rendered bold markers: {line[:80]!r}")
        elif re.match(r"^#{1,6}\s", line):
            hits.append(f"un-rendered heading marker: {line[:80]!r}")
    return {
        "name": "stray_markdown",
        "passed": len(hits) == 0,
        "detail": "; ".join(hits[:10]) if hits else "no stray markdown syntax found in rendered text",
    }


# ---------------------------------------------------------------------------
# Advisory (non-blocking): singleton lists -- likely prose misread as a list.
# ---------------------------------------------------------------------------
def check_singleton_lists(html_text: str):
    """Standard markdown (this pipeline included) always treats a line like
    '3. Detection threshold exceeded.' at the start of a paragraph as the
    first item of a NEW ordered list, even when the author meant plain
    prose that happens to start with a digit and a period -- e.g. a
    document walking through 'K1 through K10' or numbered findings written
    as sentences. This is correct, unsurprising markdown behavior (not a
    pipeline bug), so it's advisory rather than a hard failure -- a
    deliberate single-item list is rare but not impossible. But it's worth
    surfacing because the other five checks cannot see it: the content
    isn't dropped, isn't duplicated, and isn't stray syntax -- it just
    silently changed from a plain sentence into a visually distinct,
    indented list item, which changes what the reader perceives that
    sentence to mean (part of an enumerated set) that the author may not
    have intended.

    Real ordered/unordered lists in PRD-style prose are overwhelmingly 2+
    items; a list with exactly one <li> is the fingerprint of this
    misread, not proof of it -- confirm by checking the sentence in
    context, and if it's prose, escape the source as '3\\. text' (backslash
    before the period) to keep it out of list interpretation.
    """
    hits = []
    for m in re.finditer(r"<(ol|ul)\b[^>]*>(.*?)</\1>", html_text, flags=re.DOTALL):
        inner = m.group(2)
        # only count <li> that are direct children, not nested sub-lists
        li_count = len(re.findall(r"<li\b", inner))
        nested = len(re.findall(r"<(ol|ul)\b", inner))
        if li_count == 1 and nested == 0:
            text = re.sub(r"<[^>]+>", "", inner).strip()
            hits.append(text[:100])
    return {
        "name": "singleton_lists",
        "blocking": False,
        "passed": len(hits) == 0,
        "detail": (
            "no single-item lists found" if not hits else
            f"{len(hits)} single-item list(s) found -- confirm these were meant "
            f"as lists, not prose that starts with a digit+period: {hits}"
        ),
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_all(md_text: str, html_text: str):
    checks = [
        check_word_diff(md_text, html_text),
        check_tag_balance(html_text),
        check_id_nav_parity(html_text),
        check_table_list_counts(md_text, html_text),
        check_stray_markdown(html_text),
    ]
    # Advisory checks never affect the pass/fail gate or exit code -- they
    # flag things worth a human glance, not things this script can safely
    # decide are wrong on its own.
    advisories = [check_singleton_lists(html_text)]
    all_passed = all(c["passed"] for c in checks)
    return {"passed": all_passed, "checks": checks, "advisories": advisories}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_md")
    ap.add_argument("output_html")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    md_text = Path(args.input_md).read_text(encoding="utf-8")
    html_text = Path(args.output_html).read_text(encoding="utf-8")

    result = run_all(md_text, html_text)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for c in result["checks"]:
            status = "PASS" if c["passed"] else "FAIL"
            print(f"[{status}] {c['name']}: {c['detail']}")
        for a in result.get("advisories", []):
            status = "OK" if a["passed"] else "ADVISORY (non-blocking)"
            print(f"[{status}] {a['name']}: {a['detail']}")
        print()
        print("ALL CHECKS PASSED" if result["passed"] else "VERIFICATION FAILED -- see failed check(s) above")
        print(
            "\nReminder: run the fact-anchored spot check by hand -- if the source document "
            "asserts a count ('ten deterministic detections', 'eighteen tables'), confirm the "
            "rendered structure actually has that many. This script cannot know what the "
            "document claims about itself."
        )

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
