#!/usr/bin/env python3
"""
run_regression.py -- build every fixture in both modes and require verify.py to pass, then
corrupt a known-good render in three ways and require verify.py to fail. The second half
guards against a verifier that has been loosened until it passes everything.

Fixtures:
  code_fence_edge_cases.md  HTML comment and table syntax inside fences; prose starting "3. "
  yaml_in_code_fence.md     YAML list syntax inside a fence (no blank lines may be inserted)
  happy_path.md             tables/lists with no blank line before them, blockquote, TODO comment
  review_doc.md             header metadata, snake_case identifiers, IDs, pills, nested headings

Usage: python tests/run_regression.py      (exit 0 = all good)
For the browser test of commenting: node tests/test_comments.js
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "scripts"


def run(cmd):
    return subprocess.run([sys.executable, *map(str, cmd)], capture_output=True, text=True)


def main():
    out = Path(tempfile.mkdtemp(prefix="mdhtml-regress-"))
    ok = True
    for md in sorted((TESTS / "fixtures").glob("*.md")):
        for mode, extra in (("read-only", []), ("commentable", ["--comments"])):
            html = out / f"{md.stem}-{mode}.html"
            b = run([SCRIPTS / "build.py", md, html, *extra])
            if b.returncode:
                print(f"[FAIL] {md.name} {mode}: build crashed\n{b.stderr}")
                ok = False
                continue
            v = run([SCRIPTS / "verify.py", md, html])
            passed = v.returncode == 0
            ok &= passed
            print(f"[{'PASS' if passed else 'FAIL'}] {md.name} {mode}")
            if not passed:
                print(v.stdout)

    # Negative controls: verify.py must catch these.
    src = TESTS / "fixtures" / "review_doc.md"
    good = out / "review_doc-read-only.html"
    text = good.read_text(encoding="utf-8")
    corruptions = {
        "dropped paragraph": re.sub(r"<p>Every vendor is screened.*?</p>", "", text, flags=re.S),
        "table flattened to text": re.sub(r'<div class="tw"><table>.*?</table></div>',
                                          "<p>| ID | Step | Owner | Priority |</p>", text, count=1, flags=re.S),
        "unrendered bold": text.replace("<strong>Owner:</strong>", "**Owner:**"),
    }
    for name, bad in corruptions.items():
        p = out / "corrupt.html"
        p.write_text(bad, encoding="utf-8")
        caught = run([SCRIPTS / "verify.py", src, p]).returncode != 0 and bad != text
        ok &= caught
        print(f"[{'PASS' if caught else 'FAIL'}] verify catches: {name}")

    print("\nALL REGRESSION CHECKS PASSED" if ok else "\nREGRESSION FAILURES ABOVE")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
