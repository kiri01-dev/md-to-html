// Browser test for the commentable and read-only pages.
// Usage: node tests/test_comments.js   (needs python3 with markdown + beautifulsoup4, and playwright)
// Builds tests/fixtures/review_doc.md, comments on it, edits the source, rebuilds, and checks that
// comments re-anchor or are flagged as not found, never silently moved to other text.
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs'), path = require('path'), os = require('os');

const SKILL = path.resolve(__dirname, '..');
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), 'mdhtml-test-'));
const SRC = fs.readFileSync(path.join(SKILL, 'tests/fixtures/review_doc.md'), 'utf8');
let failures = 0;
function check(name, ok, detail) { console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${detail !== undefined ? ' -- ' + detail : ''}`); if (!ok) failures++; }
function build(md, html, extra) {
  const mdPath = path.join(OUT, md.name);
  fs.writeFileSync(mdPath, md.text);
  const out = path.join(OUT, html);
  execFileSync('python3', [path.join(SKILL, 'scripts/build.py'), mdPath, out, ...extra], { stdio: 'pipe' });
  const v = execFileSync('python3', [path.join(SKILL, 'scripts/verify.py'), mdPath, out]).toString();
  check(`verify ${html}`, /ALL CHECKS PASSED/.test(v));
  return 'file://' + out;
}
const COMMON = ['--doc-id', 'review-doc', '--pills', path.join(SKILL, 'assets/pills.prd.json'), '--id-pattern', '\\bON-\\d+\\b'];

async function selectPhrase(page, phrase) {
  await page.evaluate((phrase) => {
    const w = document.createTreeWalker(document.getElementById('doc'), NodeFilter.SHOW_TEXT);
    let n; while ((n = w.nextNode())) { const i = n.nodeValue.indexOf(phrase); if (i >= 0) {
      n.parentElement.scrollIntoView({ block: 'center' });
      const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + phrase.length);
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(r); return; } }
    throw new Error('phrase not found: ' + phrase);
  }, phrase);
  await page.waitForTimeout(250);
}
async function addTextComment(page, phrase, text) {
  await selectPhrase(page, phrase);
  await page.click('#add-sel');
  await page.fill('#ed-text', text);
  await page.click('#ed-save');
}
async function addBlockComment(page, locator, text) {
  await locator.scrollIntoViewIfNeeded();
  await locator.hover({ position: { x: 20, y: 8 } });
  await page.waitForTimeout(150);
  await page.click('#add-block');
  await page.fill('#ed-text', text);
  await page.keyboard.press('Control+Enter');
}
async function flags(page) {
  return page.$$eval('#list .cm', (lis) => lis.map((li) => ({
    text: li.querySelector('.cm-text').textContent,
    where: li.querySelector('.cm-where').textContent,
    flag: (li.querySelector('.cm-flag') || {}).textContent || '' })));
}

(async () => {
  const v1 = build({ name: 'review_doc.md', text: SRC }, 'v1.html', ['--comments', ...COMMON]);
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|fonts\.g/.test(m.text())) errors.push(m.text()); });

  await page.goto(v1);
  check('header meta moved into header', (await page.locator('header .meta div').count()) === 3);
  check('pills rendered', (await page.locator('td .pill.red').count()) === 1);
  await addTextComment(page, 'consolidated sanctions list', 'Which list version?');
  await addTextComment(page, 'bank details', 'Mask these in exports.');
  await addBlockComment(page, page.locator('#doc tbody tr', { hasText: 'ON-102' }), 'Finance needs a backup owner.');
  await addBlockComment(page, page.locator('#doc p', { hasText: 'Finance receives' }), 'Add the payment run calendar.');
  check('two highlights', (await page.locator('mark.hl').count()) === 2, await page.locator('mark.hl').count());
  check('four comments listed', (await page.locator('#list .cm').count()) === 4);
  const f1 = await flags(page);
  check('document ID carried on row comment', f1.some((c) => c.where.startsWith('ON-102')), JSON.stringify(f1.map((c) => c.where)));

  await page.reload(); await page.waitForTimeout(300);
  check('comments persist after reload', (await page.locator('#list .cm').count()) === 4 && (await page.locator('mark.hl').count()) === 2);

  const [dl] = await Promise.all([page.waitForEvent('download'), page.click('#btn-export')]);
  const exportPath = path.join(OUT, dl.suggestedFilename()); await dl.saveAs(exportPath);
  const exported = fs.readFileSync(exportPath, 'utf8');
  check('export file name', dl.suggestedFilename() === 'review_doc-comments.md', dl.suggestedFilename());
  check('export content', /## Comment 1 · /.test(exported) && /ID: ON-102/.test(exported) && /<!-- data: \[/.test(exported));

  // Edit the source: new paragraph at the top, reworded intake paragraph (quote kept),
  // reworded handover paragraph (block comment's text gone), new table row above ON-102.
  const v2src = SRC
    .replace('This plan describes', 'A new opening paragraph was added in this revision.\n\nThis plan describes')
    .replace('Vendors submit the intake form', 'Suppliers submit the intake form')
    .replace('Finance receives the approved record', 'Finance receives the signed record')
    .replace('| ON-102 |', '| ON-101A | Check duplicate vendors | Operations | Medium |\n| ON-102 |');
  const v2 = build({ name: 'review_doc.md', text: v2src }, 'v2.html', ['--comments', ...COMMON]);
  await page.goto(v2); await page.waitForTimeout(300);
  const f2 = await flags(page);
  const by = (t) => f2.find((c) => c.text === t) || {};
  check('unchanged paragraph: exact anchor, no flag', by('Which list version?').flag === '', by('Which list version?').flag);
  check('reworded paragraph, quote kept: re-anchored', /Re-anchored/.test(by('Mask these in exports.').flag), by('Mask these in exports.').flag);
  check('unchanged row after insert: exact anchor', by('Finance needs a backup owner.').flag === '');
  check('edited block: flagged not found, not re-pointed', /not found/.test(by('Add the payment run calendar.').flag), by('Add the payment run calendar.').flag);
  check('highlights still two', (await page.locator('mark.hl').count()) === 2);
  check('row bar on ON-102 only', (await page.locator('tr.has-comment').count()) === 1 && /ON-102/.test(await page.locator('tr.has-comment').textContent()));

  await page.click('#btn-clear'); await page.click('#btn-clear');
  check('delete all', (await page.locator('#list .cm').count()) === 0 && (await page.locator('mark.hl').count()) === 0);
  await page.setInputFiles('#file-import', exportPath); await page.waitForTimeout(400);
  check('import restores comments', (await page.locator('#list .cm').count()) === 4);

  // Read-only page
  const ro = build({ name: 'review_doc.md', text: SRC }, 'ro.html', ['--pills', path.join(SKILL, 'assets/pills.prd.json')]);
  await page.goto(ro);
  check('read-only: no comment layer', (await page.locator('#panel, .bar, #editor, [data-bid], [data-block]').count()) === 0);
  check('read-only: no scripts', (await page.locator('script').count()) === 0);
  const navOk = await page.evaluate(() => [...document.querySelectorAll('nav.toc a')].every((a) => document.getElementById(a.getAttribute('href').slice(1))));
  check('read-only: every nav link resolves', navOk);

  // Phone width
  for (const [name, url] of [['commentable', v2], ['read-only', ro]]) {
    const m = await browser.newPage({ viewport: { width: 390, height: 844 } });
    await m.goto(url); await m.waitForTimeout(200);
    const overflow = await m.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    check(`${name} at 390px: no horizontal page scroll`, overflow <= 0, overflow);
    await m.close();
  }
  check('no page errors', errors.length === 0, JSON.stringify(errors));
  await browser.close();
  console.log(`\n${failures === 0 ? 'ALL BROWSER CHECKS PASSED' : failures + ' CHECK(S) FAILED'}  (artifacts in ${OUT})`);
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
