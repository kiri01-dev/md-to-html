---
name: md-to-html
description: Turn a Markdown (.md) file into a polished standalone HTML page, either commentable (reviewers select text or click + to leave comments that save in the browser and export as a file) or read-only (clean page for people to read). Rendering is done by script and verified against the source, so no content is dropped. Use this whenever the user wants an .md file (PRD, plan, spec, report, notes) as HTML, wants a document "for review", "to get feedback on", "that people can comment on", or "to share/read", wants an existing HTML render regenerated after the .md changed, or brings back an exported comments file to act on. Use it even if they never say "convert" or "HTML", for example "make this plan reviewable" or "turn the PRD into a page". Replaces prd-md-to-html-converter. Not for PDF, Word, or slide decks.
---

# Markdown to HTML (commentable or read-only)

One script renders the page; another proves the content survived. Never hand-write or hand-edit the HTML: change the Markdown or the flags and rebuild. That keeps output deterministic, cheap, and identical every time.

## Two modes

| Mode | Flag | For | What the page has |
|---|---|---|---|
| Read-only | (default) | Sharing a finished document | Header, sticky contents nav, section cards, tables, callouts. No JavaScript. |
| Commentable | `--comments` | Collecting review feedback | Everything above, plus a comment toolbar, comment panel, text and block comments, export, import |

If the user has not said which one, ask one short question before building: "Commentable (for review) or read-only (for reading)?" Build both only if they ask for both. Words like review, feedback, comment, markup mean commentable; share, publish, send, read mean read-only.

## Workflow

### 1. Get the source

Read the .md the user named. If it lives in a connected folder and the scripts run in a different environment from that folder (for example the cloud workspace), stage the file once, build there, then write the HTML back beside the source. The scripts need Python 3 with `markdown` and `beautifulsoup4` (`pip install --break-system-packages markdown beautifulsoup4`).

Mounted copies of synced folders have been seen to lag mid-file. If the byte count of the staged copy differs from the device's, re-stage before building.

### 2. Build

```bash
python scripts/build.py INPUT.md [OUTPUT.html] [--comments] [options]
```

Default output sits beside the input: `<name>.html` for read-only, `<name>-commentable.html` for commentable.

| Option | Default | Use when |
|---|---|---|
| `--title T` | the document's single `#` heading, else file name | The heading is missing or unsuitable |
| `--eyebrow TEXT` | none | The user wants a small label above the title (company, programme) |
| `--meta auto\|none` | auto | auto moves a short block of `**Label:** value` lines directly under the title into the header. Use none if that block should stay in the body |
| `--pills FILE.json` | none | Status words in table cells should show as coloured pills. Map exact cell text to red, amber, blue, green or grey. `assets/pills.prd.json` is a ready set (High, Medium, Low, New, Done, Blocked...) |
| `--id-pattern REGEX` | none | The document has IDs (requirements, stages, tickets). Each comment then carries the nearest ID, from its own block or the closest heading above. Example: `'\b[A-Z]{1,4}-\d+\b'` |
| `--doc-id ID` | file name | Two different documents share a file name. Otherwise leave it, see step 5 |
| `--callouts FILE.json` | `assets/callouts.default.json` | The document has its own kinds of HTML-comment notes |
| `--no-hard-breaks` | hard breaks on | The Markdown is hard-wrapped at a fixed width, so single newlines should become spaces |

What the build does, so you can explain results:

- Missing blank lines before tables and lists are fixed first, with fenced code protected, so tables do not flatten into pipe text.
- `<!-- comments -->` in the source become visible callouts (TODO, TBD and "open question" show as Open question; others as Note). `<!-- embed: diagram.html -->` inlines that HTML fragment, path relative to the .md, for a hand-made diagram.
- A document with several `#` headings is treated as using `#` for sections: every heading shifts down one level and the title comes from `--title` or the file name.
- Each `##` heading starts a section card; content before the first one becomes an intro card. The nav lists `##` and `###` headings.

### 3. Verify (required)

```bash
python scripts/verify.py INPUT.md OUTPUT.html
```

Do not tell the user the page is ready until this exits 0. It checks:

1. **Word diff**: source words missing from the page (tolerance 2%). Catches dropped content anywhere.
2. **Tag balance**: the HTML is well formed.
3. **IDs and nav**: no duplicate ids; every `##`/`###` heading has a nav link and every link has a heading.
4. **Table and list counts**: tables and list items in the source appear in the page.
5. **Stray Markdown**: no leaked `**`, `|` rows, `#` or list markers in rendered text (code and table cells excluded where those are legitimate).

It also prints a non-blocking advisory for single-item lists. That usually means a sentence starting "3. " became a list; if it was prose, escape it in the source as `3\.` and rebuild.

On failure, read which check failed and why, fix the cause (almost always the source structure), rebuild, and tell the user what was wrong. If the document states its own counts ("ten detections", "eighteen tables"), confirm the page has that many; no script can know what a document claims about itself.

### 4. Deliver

Put the HTML beside the source .md. When writing into a user's connected folder from another environment, confirm the file landed by comparing a checksum (`md5sum`) on the device with the one you built; a write has been seen to report success while leaving an older version.

Tell the user in one or two sentences what was built and where. For a commentable page, add how it is used:

- Open the file in Chrome or Edge. Select text and click **Comment**, or hover a paragraph, row, heading or code block and click **+**.
- Comments save in that browser automatically. They are not inside the HTML file, so sending the file does not send comments.
- To share feedback, click **Save comments as file** (downloads `<name>-comments.md`) or **Copy comments**, and send that. **Load comments file** merges files from several reviewers.

Do not publish the page as a claude.ai artifact unless the user asks. The commentable page is self-contained on purpose; claude.ai artifact comments did not work for this use and are not a dependency.

### 5. Rebuilding after the Markdown changes

Rebuild with the same command. Keep the default `--doc-id` (or whatever was used before) so reviewers' saved comments reappear. Never change the doc id to "reset" comments.

Comments survive edits because each block's id is a hash of its own text, not its position. On load:

- Block unchanged: the comment sits exactly where it was, even if content was inserted above.
- Block reworded but the highlighted phrase still exists (same section searched first): the comment moves to it and shows **Re-anchored after an edit**.
- Text gone: the comment stays in the panel with its original quote and shows **Text not found in this version**. It is never attached to different text.

### 6. Acting on a returned comments file

A `-comments.md` export has one `## Comment N · <section>` per comment, an `ID:` line when `--id-pattern` was used, an `Anchor: text not found` line for orphans, the quoted text, the comment, and a trailing `<!-- data: [...] -->` JSON array (`--` is written as `- -`). Use the readable part to plan edits to the .md; use the JSON for exact fields (`quote`, `section`, `ref`, `resolved`). Skip resolved comments unless asked. After editing the .md, rebuild and verify.

## Files

- `scripts/build.py`: the renderer (preprocess, convert, header, sections, pills, block ids, assembly)
- `scripts/preprocess.py`: fence protection, blank-line repair, HTML-comment extraction
- `scripts/verify.py`: the five blocking checks and the advisory
- `assets/shell.html`: page frame, typography, colour tokens (light theme, IBM Plex with system fallbacks)
- `assets/comments_bar.html`, `comments_panel.html`, `comments_app.html`: the comment layer (markup, CSS, JavaScript), added only with `--comments`
- `assets/callouts.default.json`, `assets/pills.prd.json`: default callout rules and an example pill map
- `tests/run_regression.py`: builds every fixture in both modes, and checks verify.py still catches three deliberate corruptions. Run after changing any script.
- `tests/test_comments.js`: Playwright test of commenting, persistence, export, import, re-anchoring after edits, read-only output and phone width. Run after changing the comment layer.

When changing the look, edit `assets/shell.html` (and the comment CSS in `comments_app.html`), not the body content, so verify.py results stay meaningful.
