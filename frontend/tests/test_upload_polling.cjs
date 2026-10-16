// Upload polling / slow-state test. Real Chromium, MOCKED /api/ (only pathname starting /api/), fake clock.
// Run: node frontend/tests/test_upload_polling.cjs   (dev server on :5174; env BASE, PW_CHANNEL=msedge, SHOTS)
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const BASE = process.env.BASE || 'http://localhost:5174';
const SHOTS = process.env.SHOTS || path.join(__dirname, '..', '..', 'design-ref', 'shots');
fs.mkdirSync(SHOTS, { recursive: true });
const MIN = 60000;
const SLOW_MSG = 'Still processing. You can leave this page and check My Documents.';
const NOTE = 'Some files are still processing. Check My Documents before uploading them again.';
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64');
const results = [];
const errors = [];
const log = (step, ok, detail) => { results.push({ step, ok, detail }); console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const files = (n) => Array.from({ length: n }, (_, i) => ({ name: `f${i + 1}.png`, mimeType: 'image/png', buffer: PNG }));

// mode(id, now) -> 'done' | 'pending' | 'failed' | 'abort' | 'http500' ; now = fake ms since upload
async function setup(browser, { width = 1366, mode }) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 } });
  const page = await ctx.newPage();
  const S = { now: 0, polls: {}, posts: 0, singlePosts: 0, mode };
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  await page.addInitScript(() => localStorage.setItem('ackintel_token', 'mock.jwt'));
  const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route((url) => new URL(url).pathname.startsWith('/api/'), async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    const m = req.method();
    if (p === '/api/auth/me') return json(route, { user: { id: 'u1', username: 'tester', email: 't@x.com', role: 'user' } });
    if (p === '/api/health') return json(route, { status: 'ok' });
    if ((p === '/api/documents/bulk-upload' || p === '/api/documents/upload') && m === 'POST' && S.abortUpload) return route.abort('failed');
    if ((p === '/api/documents/bulk-upload' || p === '/api/documents/upload') && m === 'POST' && S.holdUpload) await S.holdUpload;
    if (p === '/api/documents/bulk-upload' && m === 'POST') {
      S.posts++; S.now = 0;
      const n = (req.postData() || '').split('name="documents"').length - 1 || S.nFiles || 10;
      return json(route, { results: Array.from({ length: n }, (_, i) => ({ document: { _id: `doc-${i + 1}` } })) }, 201);
    }
    if (p === '/api/documents/upload' && m === 'POST') { S.singlePosts++; S.now = 0; return json(route, { document: { _id: 'single-1' } }, 201); }
    if (p === '/api/documents' && m === 'GET') return json(route, { documents: [], totalDocuments: 0, totalPages: 1, currentPage: 1 });
    const mm = p.match(/^\/api\/documents\/([^/]+)$/);
    if (mm && m === 'GET') {
      const id = mm[1];
      (S.polls[id] ||= []).push(S.now);
      const r = S.mode(id, S.now);
      if (r === 'abort') return route.abort('failed');
      if (r === 'http500') return json(route, { message: 'boom' }, 500);
      const base = { _id: id, documentType: 'Tax Invoice', originalName: id + '.png' };
      if (r === 'done') return json(route, { document: { ...base, uploadStatus: 'processed', taxInvoiceNo: 'INV' + id, referenceNo: 'R1', date: '2026-01-05' } });
      if (r === 'failed') return json(route, { document: { ...base, uploadStatus: 'failed', processingError: 'OCR could not read this file' } });
      return json(route, { document: { ...base, uploadStatus: 'uploaded' } });
    }
    return json(route, {});
  });
  await page.clock.install();
  return { ctx, page, S };
}
// advance fake time in small steps so timers + real async mock responses interleave
async function adv(page, S, ms, step = 1000) {
  for (let t = 0; t < ms; t += step) { await page.clock.runFor(step); S.now += step; await sleep(12); }
  await sleep(40);
}
const bodyText = (page) => page.evaluate(() => document.body.innerText);
const pollCount = (S, ids) => ids.reduce((a, id) => a + (S.polls[id] || []).length, 0);
async function startBulk(page, n) {
  await page.goto(BASE + '/upload'); await sleep(500);
  await page.getByRole('button', { name: /Bulk Upload/ }).click();
  await page.locator('input[type=file]').first().setInputFiles(files(n));
}
const uploadAll = (page) => page.getByRole('button', { name: /Upload All/ });
const slowCount = (page) => page.evaluate(() => document.body.innerText.split('You can leave this page and check My Documents.').length - 1);
const chipCount = (page) => page.evaluate(() => [...document.querySelectorAll('span')].filter((e) => /^still processing$/i.test(e.textContent.trim())).length);
// review shows one item at a time: step through all, count slow messages / chips and rose styling on them
async function walkSlow(page) {
  let msgs = 0, chips = 0; const rose = [];
  for (let i = 0; i < 12; i++) {
    msgs += await slowCount(page); chips += await chipCount(page); rose.push(...(await hasRose(page)));
    const next = page.getByRole('button', { name: 'Next' });
    if (!(await next.count()) || !(await next.isEnabled())) break;
    await next.click(); await sleep(80);
  }
  return { msgs, chips, rose };
}
const hasRose = (page) => page.evaluate(() => {
  const bad = [];
  for (const el of document.querySelectorAll('*')) {
    if (el.children.length === 0 && /still processing/i.test(el.textContent)) {
      let n = el; for (let i = 0; i < 3 && n; i++, n = n.parentElement) if (/rose|red-\d/.test(n.className || '')) bad.push(n.className);
    }
  }
  return bad;
});

async function scenario(name, fn) {
  try { await fn(); } catch (e) { log(name, false, 'exception: ' + e.message.split('\n')[0]); }
}

(async () => {
  const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || undefined });
  const slow3 = ['doc-8', 'doc-9', 'doc-10'];

  await scenario('1 bulk gradual', async () => {
    const { ctx, page, S } = await setup(browser, { mode: (id, now) => (now >= Number(id.split('-')[1]) * MIN ? 'done' : 'pending') });
    await startBulk(page, 10); await uploadAll(page).click(); await sleep(300);
    await adv(page, S, 3 * MIN);
    const mid = await bodyText(page);
    await page.screenshot({ path: path.join(SHOTS, 'upload_progress_1366.png') });
    const midOk = /Processing \d\/10/.test(mid) && !/failed/i.test(mid);
    await adv(page, S, 8 * MIN);
    const t = await bodyText(page);
    log('1 bulk 10 files, one per minute -> all done, review reached, no Failed', midOk && /Review Results/.test(t) && /10\/10 processed/.test(t) && !/failed/i.test(t), `midProgressOk=${midOk} review=${/Review Results/.test(t)}`);
    await ctx.close();
  });

  await scenario('2/9 slow bulk', async () => {
    const { ctx, page, S } = await setup(browser, { mode: (id, now) => (slow3.includes(id) ? 'pending' : now >= 30000 ? 'done' : 'pending') });
    await startBulk(page, 10); await uploadAll(page).click(); await sleep(300);
    await adv(page, S, 21 * MIN);
    const t = await bodyText(page);
    const w = await walkSlow(page);
    log('2 after 20+ min: 3 rows slow with message, neutral styling', w.msgs === 3 && w.rose.length === 0 && /7\/10 processed, 3 still processing/.test(t), `messages=${w.msgs} roseHits=${w.rose.length} summary=${(t.match(/\d+\/10 processed.*/) || [''])[0]}`);
    await page.getByRole('button', { name: 'Previous' }).click({ clickCount: 1 }).catch(() => {});
    for (let i = 0; i < 12; i++) { const pv = page.getByRole('button', { name: 'Previous' }); if (await pv.isEnabled()) await pv.click(); }
    log('2 no Failed text for slow rows', !/failed/i.test(t), '');
    const before = pollCount(S, slow3);
    await adv(page, S, 10 * MIN, 2000);
    const after = pollCount(S, slow3);
    const last = Math.max(...slow3.map((i) => Math.max(...S.polls[i])));
    log('2 polling stopped after timeout', before === after, `slow-doc polls before=${before} after +10min=${after}; last poll at fake ${(last / MIN).toFixed(1)} min`);
    const note = page.getByTestId('bulk-slow-note');
    const noteOk = (await note.count()) > 0 && (await note.first().isVisible()) && (await note.first().innerText()).includes(NOTE);
    log('9 one-line slow note visible', noteOk, noteOk ? '' : 'bulk-slow-note missing or text differs');
    await page.screenshot({ path: path.join(SHOTS, 'upload_slow_bulk_1366.png') });
    await page.setViewportSize({ width: 390, height: 844 }); await sleep(300);
    await page.screenshot({ path: path.join(SHOTS, 'upload_slow_bulk_390.png') });
    const ovf1 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    await page.setViewportSize({ width: 1366, height: 900 });
    await page.getByRole('button', { name: /Start New Batch/ }).click(); await sleep(300);
    const picker = await page.locator('input[type=file]').count();
    log('9 Start New Batch returns to picker', picker > 0, `file inputs=${picker}`);
    S.nFiles = 2;
    await page.locator('input[type=file]').first().setInputFiles(files(2));
    await page.setViewportSize({ width: 390, height: 844 }); await sleep(300);
    const ovf2 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    await uploadAll(page).click(); await sleep(400);
    await adv(page, S, 10000);
    const ovf3 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    log('9 re-upload works, 390px no horizontal scroll', S.posts === 2 && ovf1 <= 0 && ovf2 <= 0 && ovf3 <= 0, `posts=${S.posts} overflow slow=${ovf1} picker=${ovf2} progress=${ovf3}`);
    await ctx.close();
  });

  await scenario('3', async () => {
    const { ctx, page, S } = await setup(browser, { mode: (id, now) => (['doc-2', 'doc-5'].includes(id) ? (now >= 20000 ? 'failed' : 'pending') : now >= 10000 ? 'done' : 'pending') });
    await startBulk(page, 10); await uploadAll(page).click(); await sleep(300);
    await adv(page, S, 60000);
    let t = await bodyText(page);
    const sum = /8\/10 processed, 2 failed/.test(t);
    await page.getByRole('button', { name: 'Next' }).click(); await sleep(200);
    t = await bodyText(page);
    log('3 server-reported failures show Failed + server text', sum && /Failed: OCR could not read this file/.test(t), `summary=${sum}`);
    await ctx.close();
  });

  for (const [num, kind] of [[4, 'abort'], [5, 'http500']]) {
    await scenario(String(num), async () => {
      const { ctx, page, S } = await setup(browser, { mode: (id, now) => (now < 30000 ? kind : now >= 60000 ? 'done' : 'pending') });
      await startBulk(page, 10); await uploadAll(page).click(); await sleep(300);
      let sawFailed = false;
      for (let i = 0; i < 14; i++) { await adv(page, S, 5000); if (/failed/i.test(await bodyText(page))) sawFailed = true; }
      const t = await bodyText(page);
      log(`${num} ${kind} polls for 30s then recover: never Failed, finishes`, !sawFailed && /10\/10 processed/.test(t), `sawFailed=${sawFailed} review=${/Review Results/.test(t)} polls(doc-1)=${(S.polls['doc-1'] || []).length}`);
      await ctx.close();
    });
  }

  await scenario('6a', async () => {
    const { ctx, page, S } = await setup(browser, { mode: (id, now) => (now >= 4 * MIN ? 'done' : 'pending') });
    await page.goto(BASE + '/upload'); await sleep(500);
    await page.locator('input[type=file]').first().setInputFiles(files(1)[0]);
    await page.getByRole('button', { name: /Upload & Process/ }).click(); await sleep(300);
    await adv(page, S, 4 * MIN + 10000);
    await adv(page, S, 3000);
    log('6a single finishes at 4 min -> navigates to /documents/single-1', /\/documents\/single-1$/.test(page.url()), page.url());
    await ctx.close();
  });

  await scenario('6b', async () => {
    const { ctx, page, S } = await setup(browser, { mode: () => 'pending' });
    await page.goto(BASE + '/upload'); await sleep(500);
    await page.locator('input[type=file]').first().setInputFiles(files(1)[0]);
    await page.getByRole('button', { name: /Upload & Process/ }).click(); await sleep(300);
    await adv(page, S, 4 * MIN);
    const early = await page.getByTestId('single-slow').count();
    await adv(page, S, MIN + 15000);
    const blk = page.getByTestId('single-slow');
    const shown = (await blk.count()) > 0 && (await blk.first().innerText()).includes(SLOW_MSG);
    const cls = shown ? await blk.first().evaluate((e) => e.outerHTML) : '';
    const redBox = await page.evaluate(() => [...document.querySelectorAll('main [class*="rose-"]')].map((e) => e.textContent.trim().slice(0, 60)));
    log('6b at 5 min neutral single-slow block, no red error box', early === 0 && shown && !/rose-/.test(cls) && redBox.length === 0, `notShownEarly=${early === 0} shown=${shown} roseInBlock=${/rose-/.test(cls)} roseElsewhere=${JSON.stringify(redBox)}`);
    await page.screenshot({ path: path.join(SHOTS, 'upload_slow_single_1366.png') });
    await page.setViewportSize({ width: 390, height: 844 }); await sleep(300);
    await page.screenshot({ path: path.join(SHOTS, 'upload_slow_single_390.png') });
    await page.setViewportSize({ width: 1366, height: 900 });
    const before = (S.polls['single-1'] || []).length;
    await adv(page, S, 5 * MIN, 2000);
    const after = (S.polls['single-1'] || []).length;
    log('6b single polling stopped', before === after && before > 0, `polls before=${before} after +5min=${after}`);
    const open = page.getByRole('button', { name: 'Open My Documents' }).or(page.getByRole('link', { name: 'Open My Documents' }));
    await open.first().click(); await sleep(500);
    log('6b Open My Documents navigates to /documents', /\/documents$/.test(page.url()), page.url());
    await ctx.close();
  });

  await scenario('7', async () => {
    const { ctx, page, S } = await setup(browser, { mode: () => 'pending' });
    S.nFiles = 5;
    await startBulk(page, 5); await uploadAll(page).click(); await sleep(300);
    await adv(page, S, 30000);
    const errsBefore = errors.length;
    const link = page.locator('a[href="/documents"]').first();
    if (await link.count()) await link.click();
    else await page.evaluate(() => { history.pushState({}, '', '/documents'); window.dispatchEvent(new PopStateEvent('popstate')); });
    await sleep(500);
    const url = page.url();
    const ids = ['doc-1', 'doc-2', 'doc-3', 'doc-4', 'doc-5'];
    const before = pollCount(S, ids);
    await adv(page, S, 5 * MIN, 2000);
    const after = pollCount(S, ids);
    log('7 navigate away mid-poll: polling stops, no errors', /\/documents$/.test(url) && before === after && errors.length === errsBefore, `url=${url} polls before=${before} after=${after} newErrors=${errors.length - errsBefore}`);
    await ctx.close();
  });

  await scenario('8', async () => {
    const { ctx, page, S } = await setup(browser, { mode: (id) => (slow3.includes(id) ? 'pending' : 'done') });
    await startBulk(page, 10); await uploadAll(page).click(); await sleep(300);
    await adv(page, S, 4000);
    await page.clock.fastForward(25 * MIN); S.now += 25 * MIN; await sleep(100);
    for (let i = 0; i < 4; i++) await adv(page, S, 3000);
    const t = await bodyText(page);
    const w = await walkSlow(page); const n = w.msgs;
    const last = Math.max(...slow3.map((i) => Math.max(...S.polls[i])));
    log('8 one 25-min jump + small ticks -> 3 rows slow (time-based)', n === 3 && w.rose.length === 0 && !/failed/i.test(t), `'Still processing.' messages=${n} failedText=${/failed/i.test(t)} lastPollFake=${(last / MIN).toFixed(1)}min`);
    await ctx.close();
  });

  await scenario('10', async () => {
    const { ctx, page, S } = await setup(browser, { mode: () => 'pending' });
    await startBulk(page, 3);
    await uploadAll(page).dblclick(); await sleep(600);
    log('10 double click Upload All -> exactly one bulk-upload POST', S.posts === 1, `posts=${S.posts}`);
    await ctx.close();
  });

  const noise = /Failed to load resource|net::ERR|WebSocket|\[vite\]|status of 500|ERR_FAILED|Network Error/i;
  const real = errors.filter((e) => !noise.test(e));
  await scenario('11 bulk upload request gets no answer', async () => {
    const { ctx, page, S } = await setup(browser, { mode: () => 'pending' });
    S.abortUpload = true;
    await startBulk(page, 3); await uploadAll(page).click(); await sleep(800);
    const t = await bodyText(page);
    const failed = /\bfailed\b/i.test(t.replace(/Upload may.*/i, ''));
    log('11 no-answer bulk upload shows the neutral message, never Failed', !failed && /may have gone through/i.test(t) && /still processing/i.test(t), `failedText=${failed} unconfirmed=${/may have gone through/i.test(t)}`);
    await ctx.close();
  });

  await scenario('12 single upload request gets no answer', async () => {
    const { ctx, page, S } = await setup(browser, { mode: () => 'pending' });
    S.abortUpload = true;
    await page.goto(BASE + '/upload'); await sleep(500);
    await page.locator('input[type=file]').first().setInputFiles(files(1)[0]);
    await page.getByRole('button', { name: /Upload & Process/ }).click(); await sleep(800);
    const block = page.getByTestId('single-slow');
    const shown = (await block.count()) === 1;
    const txt = shown ? await block.innerText() : '';
    const red = await page.evaluate(() => !!document.querySelector('main [class*="rose-"]:not(button)') && /Could not|failed/i.test(document.querySelector('main').innerText));
    log('12 no-answer single upload shows the neutral block, no red error', shown && /may have gone through/i.test(txt) && !red, `shown=${shown} red=${red}`);
    await ctx.close();
  });

  await scenario('13 leave the page while the upload request is in flight', async () => {
    const { ctx, page, S } = await setup(browser, { mode: () => 'done' });
    let release; S.holdUpload = new Promise((r) => { release = r; });
    await startBulk(page, 3); await uploadAll(page).click(); await sleep(300);
    await page.evaluate(() => { window.history.pushState({}, '', '/documents'); window.dispatchEvent(new PopStateEvent('popstate')); });
    await sleep(500);
    release(); await sleep(500);
    await adv(page, S, 60 * 1000);
    const polls = Object.values(S.polls).reduce((a, v) => a + v.length, 0);
    log('13 no poll loop is started after unmount (zero polls)', polls === 0, `polls=${polls} url=${page.url()}`);
    await ctx.close();
  });

  log('console/page errors from our code', real.length === 0, real.length ? real.slice(0, 5).join(' | ') : `none (${errors.length} ignored resource noise)`);
  await browser.close();
  const fails = results.filter((r) => !r.ok);
  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.step}`));
  console.log(`${results.length - fails.length}/${results.length} passed`);
  process.exit(fails.length ? 1 : 0);
})();
