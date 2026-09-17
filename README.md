# md-to-html

A [Claude](https://claude.com/claude-code) Agent Skill that turns a Markdown file into a polished standalone HTML page — either **commentable** (reviewers select text or click `+` to leave comments that save in the browser and export as a file) or **read-only** (a clean page for people to read).

Rendering is done by script and verified against the source, so no content is dropped.

## Install

Copy this folder into a skills directory Claude reads:

```bash
git clone https://github.com/kiri01-dev/md-to-html.git ~/.claude/skills/md-to-html
```

Or package it as a `.skill` bundle and upload it in Claude Settings → Skills.

## Requirements

Python 3 with:

```bash
pip install markdown beautifulsoup4
```

## Usage

```bash
python scripts/build.py INPUT.md [OUTPUT.html] [--comments]
```

| Mode | Flag | Output |
|---|---|---|
| Read-only | *(default)* | `<name>.html` — header, sticky contents nav, section cards, tables, callouts. No JavaScript. |
| Commentable | `--comments` | `<name>-commentable.html` — everything above, plus comment toolbar, comment panel, text and block comments, export/import. |

Common options:

| Option | Purpose |
|---|---|
| `--title T` | Override the page title |
| `--eyebrow TEXT` | Small label above the title |
| `--meta auto\|none` | Lift a `**Label:** value` block into the header |
| `--pills FILE.json` | Render status words in table cells as coloured pills (`assets/pills.prd.json` is a ready set) |

Verify a build against its source:

```bash
python scripts/verify.py INPUT.md OUTPUT.html
```

See [SKILL.md](SKILL.md) for the full instructions Claude follows.

## Layout

```
SKILL.md          skill instructions
scripts/          build.py, preprocess.py, verify.py
assets/           HTML shell, comment app, pill/callout configs
tests/            fixtures and regression runners
evals/            skill evaluation cases
```

## Tests

```bash
python tests/run_regression.py
```

## License

MIT — see [LICENSE](LICENSE).
