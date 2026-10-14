// Real-browser test of My Documents "Download All". Needs a running backend (:8000, TEST db) and vite (:5174),
// plus a seeded approved user and >=12 processed docs (see SEED_CMD).
// Env: BASE, EMAIL, PASSWORD, OUT (screenshot dir), UNZIP_PY (python exe for zip listing),
//      SEED_CMD (shell cmd invoked as `$SEED_CMD big|restore` to set 2 docs' size to 100MB / back; scenario 3 fails without it)
// Only URLs whose path starts with /api/ are intercepted.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const BASE = process.env.BASE || 'http://localhost:5174';
const EMAIL = process.env.EMAIL || 'dluser@looptest.local';
const PASSWORD = process.env.PASSWORD || 'Passw0rd!dl';
const OUT = process.env.OUT || path.join(__dirname, 'out_download_all');
const SEED = process.env.SEED_CMD;
const PY = process.env.UNZIP_PY || 'python';
fs.mkdirSync(OUT, { recursive: true });
const results = [];
const log = (step, ok, detail) => { results.push({ step, ok, detail }); console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const isDl = (u) => u.pathname === '/api/documents/download-all';

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console.error: ' + m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  let dlPosts = 0;
  page.on('request', (r) => { if (r.method() === 'POST' && isDl(new URL(r.url()))) dlPosts++; });
  const shot = (n) => page.screenshot({ path: path.join(OUT, n + '.png') });
  const btn = () => page.getByRole('button', { name: /Download All|Preparing/ });
  const gotoDocs = async () => { await page.goto(BASE + '/documents?type=Delivery%20Challan'); await page.getByRole('button', { name: /Download All \(\d+ on/ }).filter({ hasNotText: '(0 ' }).waitFor({ timeout: 15000 }); };
  const toastText = async (re) => (await page.getByText(re).first().innerText()).trim();
  const noDownload = async (act) => { let got = false; const f = () => (got = true); page.on('download', f); await act(); await sleep(800); page.off('download', f); return !got; };

  // login via UI
  await page.goto(BASE + '/login');
  await page.locator('input[type=email]').fill(EMAIL);
  await page.locator('input[type=password]').fill(PASSWORD);
  await page.locator('button[type=submit]').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'));
  await gotoDocs();
  await shot('1_list');
  const label0 = (await btn().innerText()).trim();
  log('1a list shows docs', /12 on this page/.test(label0), `button="${label0}"`);

  // ---- 1: single click, request delayed 1.5s
  const delay = async (route) => { await sleep(1500); await route.continue(); };
  await page.route((u) => isDl(u), delay);
  dlPosts = 0;
  const dlP = page.waitForEvent('download');
  await btn().click();
  await sleep(300);
  const pendingLabel = (await btn().innerText()).trim();
  const pendingDisabled = await btn().isDisabled();
  await shot('2_pending');
  const dl = await dlP;
  const zipPath = path.join(OUT, 'dl1.zip');
  await dl.saveAs(zipPath);
  await page.getByText(/files? downloaded\./).first().waitFor();
  const toast1 = await toastText(/of \d+ files? downloaded/);
  await shot('3_success');
  const out = execSync(`"${PY}" -I -c "import zipfile,sys;z=zipfile.ZipFile(sys.argv[1]);print(z.testzip());print('|'.join(z.namelist()))" "${zipPath}"`).toString().trim().split('\n');
  const names = out[1].split('|');
  log('1b pending label/disabled', pendingLabel === 'Preparing...' && pendingDisabled, `label="${pendingLabel}" disabled=${pendingDisabled}`);
  log('1c download+zip', dl.suggestedFilename() === 'documents.zip' && out[0].trim() === 'None' && names.length === 12, `file=${dl.suggestedFilename()} testzip=${out[0].trim()} entries=${names.length}: ${names.join(', ')}`);
  log('1d success toast', toast1 === '12 of 12 files downloaded.', `toast="${toast1}"`);
  await sleep(200);
  const after = (await btn().innerText()).trim();
  log('1e button restored', after === label0 && !(await btn().isDisabled()), `label="${after}"`);
  log('1f one POST', dlPosts === 1, `posts=${dlPosts}`);

  // ---- 2: double click (request still delayed 1.5s)
  await sleep(4500);
  dlPosts = 0;
  let downloads = 0;
  const onDl = () => downloads++;
  page.on('download', onDl);
  const h = await btn().elementHandle();
  await h.click(); await sleep(50); await h.click({ force: true }).catch(() => {});
  await sleep(4000);
  log('2a two clicks ~50ms apart', dlPosts === 1 && downloads === 1, `posts=${dlPosts} downloads=${downloads}`);
  await sleep(4500);
  dlPosts = 0; downloads = 0;
  await btn().dblclick();
  await sleep(4000);
  log('2b dblclick()', dlPosts === 1 && downloads === 1, `posts=${dlPosts} downloads=${downloads}`);
  page.off('download', onDl);
  await page.unroute((u) => isDl(u), delay);

  // ---- 3: real 413
  await sleep(4500);
  if (SEED) {
    execSync(`${SEED} big`);
    await gotoDocs();
    let nd;
    try {
      nd = await noDownload(async () => { await btn().click(); await page.getByText(/too large/).first().waitFor({ timeout: 8000 }); });
      const t = await toastText(/too large/);
      await shot('4_413');
      const enabled = !(await btn().isDisabled());
      log('3 real 413', t === 'Selected files are too large to download together. Select fewer documents.' && nd && enabled, `toast="${t}" noDownload=${nd} buttonEnabled=${enabled} label="${(await btn().innerText()).trim()}"`);
    } catch (e) { await shot('4_413_fail'); log('3 real 413', false, String(e).split('\n')[0]); }
    execSync(`${SEED} restore`);
    await gotoDocs();
  } else log('3 real 413', false, 'no SEED_CMD');

  // ---- 4: 429 - try a genuine race first (3 direct API downloads fired just before the UI request goes through)
  await sleep(4500);
  const token = await page.evaluate(() => localStorage.getItem('ackintel_token'));
  const H = { Authorization: 'Bearer ' + token };
  const list = await (await page.request.get(BASE + '/api/documents?limit=30', { headers: H })).json();
  const idList = (list.documents || list.items || []).map((d) => d._id || d.id);
  let uiStatus = null;
  const race = async (route) => {
    const direct = [1, 2, 3].map(() => page.request.post(BASE + '/api/documents/download-all', { headers: H, data: { documentIds: idList } }).then((r) => r.status()).catch(() => null));
    const resp = await route.fetch();
    uiStatus = resp.status();
    await route.fulfill({ response: resp });
    race.direct = await Promise.all(direct);
  };
  await page.route((u) => isDl(u), race);
  await btn().click();
  await sleep(2500);
  await page.unroute((u) => isDl(u), race);
  if (uiStatus === 429) {
    const t = await toastText(/already running/);
    await shot('5_429_real');
    log('4 429 GENUINE race', t === 'A download is already running.', `UI request got 429; direct statuses=${JSON.stringify(race.direct)}; toast="${t}"`);
  } else {
    log('4 genuine 429 race (not reproduced, using mock below)', true, `UI status=${uiStatus}; direct statuses=${JSON.stringify(race.direct)}`);
    await sleep(4500);
    const mock = (r) => r.fulfill({ status: 429, contentType: 'application/json', body: JSON.stringify({ detail: 'A download is already running.' }) });
    await page.route((u) => isDl(u), mock);
    await btn().click();
    const t = await toastText(/already running/);
    await shot('5_429_mock');
    log('4 429 (MOCKED)', t === 'A download is already running.' && !(await btn().isDisabled()), `toast="${t}"`);
    await page.unroute((u) => isDl(u), mock);
  }

  // ---- 5: 400 mocked
  await sleep(4500);
  const mock400 = (r) => r.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Select fewer documents.' }) });
  await page.route((u) => isDl(u), mock400);
  await btn().click();
  const t5 = await toastText(/Select fewer documents/);
  await shot('6_400_mock');
  log('5 400 (MOCKED)', t5 === 'Select fewer documents.' && !(await btn().isDisabled()), `toast="${t5}"`);
  await page.unroute((u) => isDl(u), mock400);

  // ---- 6: page still alive
  await gotoDocs();
  const rows = await page.getByText(/Delivery Challan/i).count();
  await shot('7_final');
  log('6 documents page still works', rows > 0, `"Delivery Challan" matches=${rows}`);
  console.log('=== CONSOLE/PAGE ERRORS ===');
  errors.forEach((e) => console.log(e));
  console.log('=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'} ${r.step}`));
  await browser.close();
  process.exit(results.every((r) => r.ok) ? 0 : 1);
})().catch((e) => { console.error('FATAL', e); process.exit(2); });
