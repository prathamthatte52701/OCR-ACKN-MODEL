// Regression: leaving a page that shows DocumentViewer (PDF) must not throw on effect cleanup.
// Usage: BASE=http://localhost:5174 node frontend/tests/test_viewer_cleanup.cjs [before]
// "before" mode only runs the reproduction (PDF + Back) and prints evidence.
// Only URLs whose path starts with /api/ are mocked; no backend needed.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const BASE = process.env.BASE || 'http://localhost:5174';
const BEFORE = process.argv[2] === 'before';
const FX = path.join(__dirname, 'fixtures_viewer');
const pdfBytes = fs.readFileSync(path.join(FX, 'a4.pdf'));
const pngBytes = fs.readFileSync(path.join(FX, 'a.png'));

const results = [];
const log = (step, ok, detail) => {
  results.push({ step, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`);
};

const USER = { _id: 'u1', id: 'u1', username: 'tester', email: 't@example.com', role: 'user', status: 'approved' };
const mkDoc = (id, kind, status = 'processed', type = 'Delivery Challan') => ({
  _id: id, userId: 'u1', documentType: type, autoName: `Doc ${id}`,
  number: '12345', taxInvoiceNo: 'INV-1', referenceNo: 'REF-1', date: '2026-01-15',
  uploadStatus: status, mimeType: kind === 'pdf' ? 'application/pdf' : 'image/png',
  originalFilename: kind === 'pdf' ? `${id}.pdf` : `${id}.png`, gridFsFileId: 'g' + id,
  size: 2048, exported: false, filePurged: false, createdAt: '2026-01-15T10:00:00Z', processedAt: '2026-01-15T10:00:05Z',
});
const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

async function newPage(browser, state) {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  await ctx.addInitScript(() => localStorage.setItem('ackintel_token', 'fake-token'));
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console.error: ' + m.text()); });
  page.on('response', (r) => { if (r.status() >= 400) errors.push(`HTTP ${r.status()} ${r.url()}`); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + (e.stack || e.message).split('\n').slice(0, 2).join(' | ')));
  const unmocked = [];
  await page.route((u) => u.pathname.startsWith('/api/'), (route) => {
    const u = new URL(route.request().url());
    const p = u.pathname.replace(/^\/api/, '');
    const method = route.request().method();
    if (p === '/auth/me') return json(route, { user: USER });
    if (p === '/health') return json(route, { status: 'ok' });
    if (method === 'GET' && p === '/documents') return json(route, { documents: [], total: 0, page: 1, pages: 1 });
    if (p === '/documents/training-stats') return json(route, { trainedCount: 0, correctedCount: 0 });
    let m;
    if ((m = p.match(/^\/documents\/([^/]+)\/download$/))) {
      const d = state.docs[m[1]];
      return route.fulfill({ status: 200, contentType: d.kind === 'pdf' ? 'application/pdf' : 'image/png', body: d.kind === 'pdf' ? pdfBytes : pngBytes });
    }
    if (method === 'POST' && p === '/documents/bulk-upload') {
      return json(route, { results: state.bulkIds.map((id) => ({ document: { _id: id } })) });
    }
    if ((m = p.match(/^\/documents\/([^/]+)$/)) && method === 'GET') {
      const d = state.docs[m[1]];
      if (!d) return json(route, { message: 'nf' }, 404);
      d.hits = (d.hits || 0) + 1;
      const status = d.uploadedFirst && d.hits <= d.uploadedFirst ? 'uploaded' : 'processed';
      return json(route, { document: mkDoc(m[1], d.kind, status, d.type) });
    }
    unmocked.push(`${method} ${p}`);
    return json(route, { message: 'unmocked' }, 404);
  });
  return { ctx, page, errors, unmocked };
}

// Land on /help (static), then client-side push to the document so Back has in-app history.
async function pushTo(page, p) {
  await page.evaluate((to) => { window.history.pushState({ usr: null, key: Math.random().toString(36).slice(2, 8), idx: (window.history.state?.idx ?? 0) + 1 }, '', to); window.dispatchEvent(new PopStateEvent('popstate', { state: {} })); }, p);
}
const boom = (page) => page.locator('text=Something went wrong').count();

async function canvasInfo(page, scope = 'body') {
  await page.waitForSelector(`${scope} canvas`, { timeout: 15000 });
  await page.waitForFunction((s) => {
    const c = document.querySelector(`${s} canvas`);
    if (!c || c.width <= 300 && c.height <= 150) return false;
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    for (let i = 0; i < d.length; i += 4 * 20) if (d[i] < 128 && d[i + 3] > 0) return true;
    return false;
  }, scope, { timeout: 15000 });
  return page.evaluate((s) => {
    const c = document.querySelector(`${s} canvas`);
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let dark = 0; for (let i = 0; i < d.length; i += 4 * 50) if (d[i] < 128 && d[i + 3] > 0) dark++;
    return { w: c.width, h: c.height, dark };
  }, scope);
}

async function check(step, page, errors, extra = {}) {
  await page.waitForTimeout(700);
  const sw = await boom(page);
  const ok = sw === 0 && errors.length === 0 && (extra.ok ?? true);
  log(step, ok, `somethingWentWrong=${sw} errors=${errors.length}${errors.length ? ' ' + JSON.stringify(errors) : ''}${extra.note ? ' ' + extra.note : ''}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const base = { docs: {}, bulkIds: [] };
  for (const [id, kind] of [['p1', 'pdf'], ['p2', 'pdf'], ['i1', 'png']]) base.docs[id] = { kind };
  base.docs.up = { kind: 'pdf', uploadedFirst: 2 };
  for (const id of ['b1', 'b2', 'b3']) { base.docs[id] = { kind: 'pdf', type: 'Tax Invoice' }; base.bulkIds.push(id); }

  // ---------- BEFORE-fix reproduction ----------
  if (BEFORE) {
    const { page, errors, ctx } = await newPage(browser, base);
    await page.goto(`${BASE}/help`); await page.waitForTimeout(800);
    await pushTo(page, '/documents/p1');
    const ci = await canvasInfo(page).catch((e) => ({ err: e.message }));
    console.log('canvas before leaving:', JSON.stringify(ci));
    await page.click('button[aria-label="Go back"]');
    await page.waitForTimeout(1000);
    const sw = await boom(page);
    console.log('somethingWentWrong count:', sw);
    console.log('errors:', JSON.stringify(errors, null, 1));
    log('BEFORE: PDF + Back reproduces error boundary', sw > 0, `errors=${errors.length}`);
    await ctx.close(); await browser.close(); return;
  }

  // ---------- AFTER ----------
  let t = await newPage(browser, base);
  let { page, errors } = t;
  await page.goto(`${BASE}/help`); await page.waitForTimeout(800);

  // (a) PDF + Back, with render/zoom/page assertions
  await pushTo(page, '/documents/p1');
  const c1 = await canvasInfo(page);
  const pctBefore = await page.locator('[data-testid="document-viewer"] [aria-live="polite"]').first().innerText();
  const w0 = c1.w;
  await page.click('button[aria-label="Zoom in"]'); await page.waitForTimeout(600);
  const pctAfter = await page.locator('[data-testid="document-viewer"] [aria-live="polite"]').first().innerText();
  const c1z = await canvasInfo(page);
  await page.click('button[aria-label="Next page"]'); await page.waitForTimeout(600);
  const pg = await page.locator('text=/Page \\d+ \\/ \\d+/').innerText();
  await page.click('button[aria-label="Previous page"]'); await page.waitForTimeout(400);
  const pg2 = await page.locator('text=/Page \\d+ \\/ \\d+/').innerText();
  await check('(a0) PDF renders (canvas non-zero, has dark pixels)', page, errors, { ok: c1.w > 0 && c1.h > 0 && c1.dark > 0, note: JSON.stringify(c1) });
  await check('(a0) zoom in works', page, errors, { ok: pctBefore !== pctAfter && c1z.w !== w0, note: `${pctBefore} -> ${pctAfter}, canvas w ${w0} -> ${c1z.w}` });
  await check('(a0) page next/prev works', page, errors, { ok: /Page 2 \/ 3/.test(pg) && /Page 1 \/ 3/.test(pg2), note: `${pg} then ${pg2}` });
  await page.click('button[aria-label="Go back"]');
  await check('(a) PDF doc + Back', page, errors, { ok: new URL(page.url()).pathname === '/help', note: 'url=' + page.url() });

  // (b) PDF then another PDF
  await pushTo(page, '/documents/p1'); await canvasInfo(page);
  await pushTo(page, '/documents/p2');
  await page.waitForFunction(() => document.body.innerText.includes('p2.pdf'), null, { timeout: 15000 });
  const c2 = await canvasInfo(page);
  await check('(b) PDF -> another PDF (canvas renders)', page, errors, { ok: c2.dark > 0, note: JSON.stringify(c2) });
  await page.click('button[aria-label="Go back"]');
  await check('(b2) Back from second PDF', page, errors);

  // (c) PDF + reload
  await pushTo(page, '/documents/p1'); await canvasInfo(page);
  await page.reload(); const c3 = await canvasInfo(page);
  await check('(c) PDF + page reload (renders again)', page, errors, { ok: c3.dark > 0, note: JSON.stringify(c3) });
  await page.click('button[aria-label="Go back"]').catch(() => {});
  await check('(c2) Back after reload', page, errors);

  // (d) PNG + Back
  await page.goto(`${BASE}/help`); await page.waitForTimeout(500);
  await pushTo(page, '/documents/i1');
  await page.waitForSelector('[data-testid="document-viewer"] img, [data-testid="document-viewer"] canvas', { timeout: 15000 });
  await check('(d0) PNG viewer shown', page, errors);
  await page.click('button[aria-label="Go back"]');
  await check('(d) PNG doc + Back', page, errors, { ok: new URL(page.url()).pathname === '/help' });

  // (e) uploaded -> processed polling then Back
  await pushTo(page, '/documents/up');
  await page.waitForFunction(() => document.querySelector('span.capitalize')?.innerText.toLowerCase() === 'processed', null, { timeout: 20000 });
  const hits = base.docs.up.hits;
  const ce = await canvasInfo(page).catch(() => null);
  await check('(e0) polled uploaded->processed, PDF renders', page, errors, { ok: !!ce && ce.dark > 0, note: `GET hits=${hits} canvas=${JSON.stringify(ce)}` });
  await page.click('button[aria-label="Go back"]');
  await check('(e) Back after polling', page, errors);

  // (g) rapid open/close 20 times
  await page.goto(`${BASE}/help`); await page.waitForTimeout(500);
  for (let i = 0; i < 20; i++) {
    await pushTo(page, `/documents/${i % 2 ? 'p2' : 'p1'}`);
    await page.waitForTimeout([0, 30, 80, 150, 300][i % 5]);
    if (i % 2) await page.click('button[aria-label="Go back"]', { timeout: 3000 }).catch(() => page.goBack());
    else await page.goBack();
    await page.waitForTimeout(20);
  }
  await page.waitForTimeout(1200);
  await check('(g) 20 rapid open/close cycles', page, errors, { ok: new URL(page.url()).pathname === '/help' && (await boom(page)) === 0, note: 'url=' + page.url() });
  await pushTo(page, '/documents/p1'); const cg = await canvasInfo(page);
  await check('(g2) viewer still renders after rapid cycles', page, errors, { ok: cg.dark > 0 });

  // (f) bulk Review Results with several PDFs, Next/Prev, then Back
  await page.goto(`${BASE}/upload`); await page.waitForTimeout(800);
  await page.click('button:has-text("Bulk Upload")');
  await page.locator('input[type=file][multiple]').setInputFiles(['b1', 'b2', 'b3'].map((n) => ({ name: `${n}.pdf`, mimeType: 'application/pdf', buffer: pdfBytes })));
  await page.click('button:has-text("Upload All")');
  await page.waitForSelector('text=Review Results', { timeout: 30000 });
  const v = '[data-testid="review-preview"]';
  const f0 = await canvasInfo(page, v);
  const n0 = await page.locator(v).getAttribute('data-filename');
  await check('(f0) Review Results shows PDF', page, errors, { ok: f0.dark > 0, note: `${n0} ${JSON.stringify(f0)}` });
  await page.click('button:has-text("Next")'); await page.waitForTimeout(800);
  const n1 = await page.locator(v).getAttribute('data-filename');
  const f1 = await canvasInfo(page, v);
  await check('(f) Next document', page, errors, { ok: n1 !== n0 && f1.dark > 0, note: `${n0} -> ${n1} ${JSON.stringify(f1)}` });
  await page.click('button:has-text("Next")'); await page.waitForTimeout(500);
  await page.click('button:has-text("Previous")'); await page.waitForTimeout(500);
  await page.click('button:has-text("Previous")'); await page.waitForTimeout(500);
  const f2 = await canvasInfo(page, v);
  await check('(f2) Next, Next, Prev, Prev', page, errors, { ok: f2.dark > 0 && (await page.locator(v).getAttribute('data-filename')) === n0 });
  await page.click('button[aria-label="Go back"]');
  await check('(f3) Back out of Review Results', page, errors);

  // single-upload preview (file chosen, then replaced / left)
  await page.goto(`${BASE}/upload`); await page.waitForTimeout(800);
  await page.locator('input[type=file]:not([multiple])').first().setInputFiles({ name: 's.pdf', mimeType: 'application/pdf', buffer: pdfBytes });
  const cs = await canvasInfo(page);
  await page.locator('input[type=file]:not([multiple])').first().setInputFiles({ name: 's2.pdf', mimeType: 'application/pdf', buffer: pdfBytes }).catch(() => {});
  await page.waitForTimeout(800);
  await page.click('button[aria-label="Go back"]');
  await check('(extra) single-upload PDF preview, swap file, Back', page, errors, { ok: cs.dark > 0 });

  console.log('\nunmocked /api calls:', JSON.stringify([...new Set(t.unmocked)]));
  console.log('=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.step}`));
  console.log('ALL ERRORS COLLECTED:', JSON.stringify(errors));
  await browser.close();
})().catch((e) => { console.error('SCRIPT CRASH', e); process.exit(1); });
