// Feature 3: Today/Week/Month/Year date-range filter on the My Documents page.
//
// The precise rolling-window boundary math (today=24h/week=7d/month=30d/
// year=365d cutoffs) is covered by a backend script that inserts documents
// with controlled createdAt timestamps directly via pymongo and hits
// GET /api/documents?range=X (not reproducible here since the public API
// never lets a client set createdAt - every upload stamps datetime.now(UTC)).
// This script instead verifies the UI: the range buttons render, clicking
// one sets ?range= in the URL (useSearchParams pattern, same as number/date/
// type), a freshly-uploaded document (createdAt ~= now) shows up under every
// range bucket since they're all supersets of "last 24h", "All" clears the
// param, and the range filter composes with the existing type tab without
// disturbing it.
const { chromium } = require('playwright');
const BASE = 'http://localhost:5174';
const results = [];
function log(step, ok, detail) {
  results.push({ step, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`);
}
const rand = Math.floor(Math.random() * 1000000);
// 1x1 red-pixel PNG, inline so this script has no external fixture-file
// dependency (unlike block_c_dashboard.cjs's hardcoded 'E:\test doc\1-D.pdf',
// which doesn't exist in every environment this suite runs in).
const SEED_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64'
);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  try {
    const email = `rangefilter_${rand}@example.com`;
    await page.request.post(`${BASE}/api/auth/signup`, { data: { username: 'RangeF', email, password: 'Test1234!' } });
    const loginResp = await page.request.post(`${BASE}/api/auth/login`, { data: { email, password: 'Test1234!' } });
    const { token } = await loginResp.json();

    // seed one real document via API upload (bypasses the UI) so the page
    // has something to filter - createdAt will be "now", so it belongs in
    // every range bucket (today/week/month/year are all supersets of 24h).
    const uploadResp = await page.request.post(`${BASE}/api/documents/upload`, {
      headers: { Authorization: `Bearer ${token}` },
      multipart: { document: { name: 'seed.png', mimeType: 'image/png', buffer: SEED_PNG }, documentType: 'Delivery Challan' },
    });
    const uploadJson = await uploadResp.json();
    log('setup: seed document uploaded', uploadResp.ok(), `status=${uploadResp.status()} id=${uploadJson.document && uploadJson.document._id}`);

    // log in through the UI so localStorage/auth state is set for page navigation
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await page.fill('input[autocomplete="email"]', email);
    await page.fill('input[autocomplete="current-password"]', 'Test1234!');
    await page.click('button[type="submit"]');
    await page.waitForURL(BASE + '/', { timeout: 10000 });

    await page.goto(`${BASE}/documents?type=Delivery+Challan`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(800);

    const hasNoRangeYet = !page.url().includes('range=');
    log('Documents page loads with no range param by default', hasNoRangeYet, `url=${page.url()}`);

    const rangeButtons = ['Today', 'This Week', 'This Month', 'This Year'];
    for (const label of rangeButtons) {
      const visible = await page.locator(`button:has-text("${label}")`).isVisible().catch(() => false);
      log(`"${label}" range button is visible`, visible);
    }
    // exact match - "Delivery Challan" also contains "all" as a case-insensitive
    // substring ("Ch-all-an"), so a plain :has-text("All") locator is ambiguous.
    const allButton = page.getByRole('button', { name: 'All', exact: true });
    const allVisible = await allButton.isVisible().catch(() => false);
    log('"All" range button is visible', allVisible);

    for (const [label, param] of [['Today', 'today'], ['This Week', 'week'], ['This Month', 'month'], ['This Year', 'year']]) {
      await page.click(`button:has-text("${label}")`);
      await page.waitForURL(new RegExp(`range=${param}`), { timeout: 5000 }).catch(() => {});
      const urlOk = page.url().includes(`range=${param}`);
      log(`Clicking "${label}" sets ?range=${param} in URL`, urlOk, `url=${page.url()}`);
      const typePreserved = page.url().includes('type=Delivery');
      log(`Clicking "${label}" preserves existing type=Delivery+Challan param`, typePreserved, `url=${page.url()}`);
      await page.waitForTimeout(500);
      const emptyState = await page.locator('text=No documents yet').isVisible().catch(() => false);
      log(`range=${param} still shows the just-uploaded doc (createdAt=now is inside every window)`, !emptyState);
    }

    // "All" clears the range param but keeps type
    await allButton.click();
    await page.waitForTimeout(500);
    const rangeCleared = !page.url().includes('range=');
    const typeStillThere = page.url().includes('type=Delivery');
    log('"All" clears range= from URL while keeping type=', rangeCleared && typeStillThere, `url=${page.url()}`);

    // range param survives across the existing type-tab switch (composability)
    await page.click('button:has-text("This Month")');
    await page.waitForURL(/range=month/, { timeout: 5000 }).catch(() => {});
    await page.click('button:has-text("Tax Invoice")');
    await page.waitForTimeout(500);
    const bothParamsPresent = page.url().includes('range=month') && page.url().includes('type=Tax');
    log('Switching document-type tab preserves an active range filter', bothParamsPresent, `url=${page.url()}`);

    // cleanup
    const purgeResp = await page.request.delete(`${BASE}/api/documents/purge-all`, { headers: { Authorization: `Bearer ${token}` } });
    log('cleanup: purge-all removed seeded test data', purgeResp.ok(), `status=${purgeResp.status()}`);
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - failed}/${results.length} passed`);
})();
