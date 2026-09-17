#!/usr/bin/env python3
"""
build.py -- render a Markdown file as a standalone HTML page, in one of two modes:

  read-only    (default)  clean page for people to read: header, contents nav, sections
  commentable  (--comments) same page plus a review layer: select text or click + on a
               block to comment; comments autosave in the browser, export to a .md file,
               and re-import to merge several reviewers

The model never hand-writes the HTML. This script is the only renderer, so output is
deterministic for a given source and flag set. Run verify.py on the result afterwards.

Usage:
  python build.py INPUT.md [OUTPUT.html] [--comments]
                  [--title T] [--eyebrow TEXT] [--meta auto|none]
                  [--pills pills.json] [--id-pattern REGEX] [--doc-id ID]
                  [--callouts callouts.json] [--no-hard-breaks]

Output default: <input stem>.html (read-only) or <input stem>-commentable.html, beside the input.
"""
import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path

import markdown
from bs4 import BeautifulSoup, NavigableString, Tag

SCRIPT_DIR = Path(__file__).resolve().parent
ASSETS = SCRIPT_DIR.parent / "assets"
sys.path.insert(0, str(SCRIPT_DIR))
import preprocess as pp  # noqa: E402

COMMENT_PLACEHOLDER_RE = re.compile(r"^MDHTML_COMMENT_PLACEHOLDER_(\d+)$")
EMBED_RE = re.compile(r"^\s*embed:\s*(\S.*?)\s*$", re.I)
# Elements a reviewer can comment on as a whole block.
BLOCK_TAGS = ["p", "li", "tr", "pre", "blockquote", "h2", "h3", "h4", "h5", "h6"]
META_LINE_RE = re.compile(r"^\s*(<strong>)?[^:<>]{1,40}(</strong>)?:(</strong>)?\s*\S.{0,160}$")


def slugify(value, separator="-"):
    """Single source of truth for heading ids (nav hrefs come from toc_tokens of the same pass)."""
    value = re.sub(r"&\w+;", "", value)
    value = value.lower()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"[\s_]+", separator, value)
    return value.strip(separator)


def classify(text, source, rules):
    for rule in rules:
        if rule.get("source") == source and re.search(rule["match"], text):
            return rule
    return None


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
def render_markdown(md_text, hard_breaks):
    exts = ["tables", "toc", "fenced_code", "sane_lists"]
    if hard_breaks:
        exts.append("nl2br")
    md = markdown.Markdown(extensions=exts,
                           extension_configs={"toc": {"slugify": slugify, "permalink": False}})
    return md.convert(md_text)


def surface_comments(soup, comments, rules, base_dir, embeds_used):
    """HTML comments in the source become visible callouts (authored notes should not vanish).
    A comment of the form <!-- embed: path/to/fragment.html --> is replaced by that file."""
    for p in soup.find_all("p"):
        m = COMMENT_PLACEHOLDER_RE.match(p.get_text().strip())
        if not m:
            continue
        text = comments[int(m.group(1))]
        em = EMBED_RE.match(text)
        if em:
            path = (base_dir / em.group(1)).resolve()
            if not path.is_file():
                raise SystemExit(f"embed file not found: {path}")
            frag = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
            div = soup.new_tag("div", attrs={"class": "embed", "data-block": ""})
            for child in list(frag.contents):
                div.append(child)
            p.replace_with(div)
            embeds_used.append(str(path))
            continue
        rule = classify(text, "comment", rules) or {"css_class": "note", "title": "Note"}
        div = soup.new_tag("div", attrs={"class": f"callout {rule['css_class']}", "data-block": ""})
        if rule.get("title"):
            t = soup.new_tag("div", attrs={"class": "callout-title"})
            t.string = rule["title"]
            div.append(t)
        body = soup.new_tag("p")
        body.string = text
        div.append(body)
        p.replace_with(div)


def normalise_headings(soup):
    """One h1 = document title. Several h1s = the doc uses h1 for sections, so shift every
    heading down one level; the title then comes from --title or the file name."""
    h1s = soup.find_all("h1")
    if len(h1s) <= 1:
        return h1s[0] if h1s else None
    for level in range(5, 0, -1):
        for h in soup.find_all(f"h{level}"):
            h.name = f"h{level + 1}"
    return None


def extract_header(soup, h1, meta_mode):
    title_html, meta_html = None, ""
    if h1 is not None:
        title_html = "".join(str(c) for c in h1.contents)
        nxt = h1.find_next_sibling()
        h1.decompose()
        if meta_mode == "auto" and nxt is not None and nxt.name == "p":
            inner = "".join(str(c) for c in nxt.contents)
            lines = [l.strip() for l in re.split(r"<br\s*/?>|\n", inner) if l.strip()]
            if 0 < len(lines) <= 8 and all(META_LINE_RE.match(l) for l in lines):
                meta_html = "".join(f"<div>{l}</div>" for l in lines)
                after = nxt.find_next_sibling()
                nxt.decompose()
                if after is not None and after.name == "hr":
                    after.decompose()
    return title_html, meta_html


def wrap_tables(soup):
    for table in soup.find_all("table"):
        table.wrap(soup.new_tag("div", attrs={"class": "tw"}))


def apply_pills(soup, pills):
    if not pills:
        return
    for td in soup.find_all("td"):
        txt = td.get_text().strip()
        if txt in pills and len(td.contents) >= 1:
            span = soup.new_tag("span", attrs={"class": f"pill {pills[txt]}"})
            for child in list(td.contents):
                span.append(child.extract())
            td.append(span)


def sectionize(soup):
    """Wrap each h2 and everything after it in <section data-sec>. Content before the first
    h2 becomes an intro section. Returns the new soup."""
    out = BeautifulSoup("", "html.parser")
    current = None
    for node in list(soup.contents):
        if isinstance(node, NavigableString) and not node.strip():
            continue
        if isinstance(node, Tag) and node.name == "h2":
            current = out.new_tag("section", attrs={"data-sec": node.get("id", "")})
            out.append(current)
        elif current is None:
            current = out.new_tag("section", attrs={"class": "intro", "data-sec": "intro"})
            out.append(current)
        current.append(node.extract())
    return out


def stamp_blocks(soup, id_regex):
    """Give every commentable block a content-derived id, so comments survive edits elsewhere
    in the document. Identical text in two blocks is disambiguated by section, then by order.
    With --id-pattern, also stamp the nearest document ID as data-ref for exports: an ID at the
    start of the block, else the closest heading above that has one, else any ID in the block."""
    blocks = soup.find_all(lambda t: t.name in BLOCK_TAGS or t.has_attr("data-block"))
    seen = {}
    last_heading_ref = {}
    for b in blocks:
        text = norm(b.get_text())
        sec = b.find_parent("section")
        sec_id = sec.get("data-sec", "") if sec else ""
        bid = "b" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        if bid in seen:
            bid = "b" + hashlib.sha1((sec_id + "\x00" + text).encode("utf-8")).hexdigest()[:8]
        n = seen.get(bid, 0)
        seen[bid] = n + 1
        if n:
            bid = f"{bid}-{n + 1}"
        if b.has_attr("data-block"):
            del b["data-block"]
        b["data-bid"] = bid
        if id_regex:
            m = id_regex.search(text)
            if b.name in ("h2", "h3", "h4", "h5", "h6"):
                level = int(b.name[1])
                for lv in list(last_heading_ref):
                    if lv >= level:
                        del last_heading_ref[lv]
                if m:
                    last_heading_ref[level] = m.group(0)
            # An ID at the start of the block (a row's ID column, "K3: ...") names the block itself.
            # An ID further in is usually a cross-reference, so the heading's ID wins over it.
            if m and m.start() <= 24:
                ref = m.group(0)
            elif last_heading_ref:
                ref = last_heading_ref[max(last_heading_ref)]
            else:
                ref = m.group(0) if m else None
            if ref:
                b["data-ref"] = ref
    return len(blocks)


def build_nav(soup):
    links = []
    for h in soup.find_all(["h2", "h3"]):
        if not h.get("id"):
            continue
        cls = "nav-link nav-sub" if h.name == "h3" else "nav-link"
        links.append(f'<a class="{cls}" href="#{h["id"]}">{html.escape(h.get_text().strip())}</a>')
    return "\n".join(links)


# ---------------------------------------------------------------------------
def build(args):
    src = Path(args.input_md).resolve()
    raw = src.read_text(encoding="utf-8")
    version = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]

    rules = json.loads(Path(args.callouts or ASSETS / "callouts.default.json").read_text(encoding="utf-8"))
    pills = json.loads(Path(args.pills).read_text(encoding="utf-8")) if args.pills else None
    id_regex = re.compile(args.id_pattern) if args.id_pattern else None

    text, comments = pp.preprocess(raw)
    body = render_markdown(text, hard_breaks=not args.no_hard_breaks)
    soup = BeautifulSoup(body, "html.parser")

    embeds = []
    surface_comments(soup, comments, rules, src.parent, embeds)
    h1 = normalise_headings(soup)
    title_html, meta_html = extract_header(soup, h1, args.meta)
    if args.title:
        title_html = html.escape(args.title)
    if not title_html:
        title_html = html.escape(src.stem.replace("_", " ").replace("-", " "))
    title_text = BeautifulSoup(title_html, "html.parser").get_text().strip()

    wrap_tables(soup)
    apply_pills(soup, pills)
    for hr in soup.find_all("hr"):
        # Section boxes already separate content; a rule directly before an h2 is redundant.
        nxt = hr.find_next_sibling()
        if nxt is None or nxt.name == "h2":
            hr.decompose()
    soup = sectionize(soup)

    commentable = bool(args.comments)
    if commentable:
        n_blocks = stamp_blocks(soup, id_regex)
    else:
        n_blocks = 0
        for t in soup.find_all(attrs={"data-block": True}):
            del t["data-block"]
    nav = build_nav(soup)

    shell = (ASSETS / "shell.html").read_text(encoding="utf-8")
    eyebrow = f'<p class="eyebrow">{html.escape(args.eyebrow)}</p>' if args.eyebrow else ""
    doc_id = args.doc_id or slugify(src.stem) or "document"
    if commentable:
        cfg = json.dumps({"docId": doc_id, "title": title_text, "version": version,
                          "fileBase": src.stem}).replace("</", "<\\/")
        bar = (ASSETS / "comments_bar.html").read_text(encoding="utf-8")
        panel = (ASSETS / "comments_panel.html").read_text(encoding="utf-8")
        app = (ASSETS / "comments_app.html").read_text(encoding="utf-8").replace("@@CONFIG@@", cfg)
    else:
        bar = panel = app = ""

    page = shell
    for k, v in [("@@TITLE@@", html.escape(title_text)), ("@@EYEBROW@@", eyebrow),
                 ("@@H1@@", title_html), ("@@META@@", meta_html), ("@@BAR@@", bar),
                 ("@@NAV@@", nav), ("@@PANEL@@", panel), ("@@APP@@", app)]:
        page = page.replace(k, v)
    page = page.replace("@@BODY@@", str(soup))  # last, so document text can never be read as a placeholder

    if args.output_html:
        out = Path(args.output_html)
    else:
        out = src.with_name(src.stem + ("-commentable.html" if commentable else ".html"))
    out.write_text(page, encoding="utf-8")

    print(f"wrote {out}")
    print(f"mode={'commentable' if commentable else 'read-only'} title={title_text!r} "
          f"sections={len(soup.find_all('section'))} version={version}")
    if commentable:
        print(f"commentable blocks={n_blocks} storage key=mdhtml:{doc_id}:comments")
    if embeds:
        print(f"embedded fragments: {embeds}")
    if comments:
        print(f"html comments surfaced: {len(comments) - len(embeds)} callout(s)")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_md")
    ap.add_argument("output_html", nargs="?")
    ap.add_argument("--comments", action="store_true", help="build the commentable review page")
    ap.add_argument("--title", help="override the page title (default: the document's h1, else file name)")
    ap.add_argument("--eyebrow", help="small uppercase label above the title; none by default")
    ap.add_argument("--meta", choices=["auto", "none"], default="auto",
                    help="auto: a short 'Label: value' block right under the h1 moves into the header")
    ap.add_argument("--pills", help='JSON map of exact table-cell text to a colour: {"High": "red"}; '
                                    "colours: red amber blue green grey")
    ap.add_argument("--id-pattern", help=r"regex for document IDs to carry into comment exports, e.g. '\b[A-Z]{1,4}-\d+\b'")
    ap.add_argument("--doc-id", help="comment storage id; default is the input file name. Keep it stable across rebuilds")
    ap.add_argument("--callouts", help="custom callout rules JSON (see assets/callouts.default.json)")
    ap.add_argument("--no-hard-breaks", action="store_true",
                    help="treat single newlines as spaces (default keeps them as line breaks)")
    build(ap.parse_args())


if __name__ == "__main__":
    main()
