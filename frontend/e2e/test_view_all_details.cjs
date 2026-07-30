const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const path = require('path');
const BASE = 'http://localhost:5174';
const PYTHON = 'E:\\Python OCR ACKN Model\\venv\\Scripts\\python.exe';
const SEED_SCRIPT = path.join(
  'C:\\Users\\Pratham\\AppData\\Local\\Temp\\claude\\E--Python-OCR-ACKN-Model\\844d6fa6-3000-44f5-8a6d-8348a8f35089\\scratchpad',
  'seed_docs.py'
);
const results = [];
function log(step, ok, detail) {
  results.push({ step, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`);
}
const rand = Math.floor(Math.random() * 1000000);

function seedDocs(specs) {
  const out = execFileSync(PYTHON, [SEED_SCRIPT], { input: JSON.stringify(specs), encoding: 'utf8' });
  return JSON.parse(out.trim());
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  let ctx1, ctx2;

  try {
    // --- User 1: main test user with varied documents ---
    const email1 = `viewall_${rand}@example.com`;
    const password = 'Test1234!';
    ctx1 = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page1 = await ctx1.newPage();

    await page1.request.post(`${BASE}/api/auth/signup`, { data: { username: 'VaU1', email: email1, password } });
    const loginResp1 = await page1.request.post(`${BASE}/api/auth/login`, { data: { email: email1, password } });
    const loginJson1 = await loginResp1.json();
    const user1Id = loginJson1.user.id;
    log('setup: user1 signup+login', Boolean(user1Id), `userId=${user1Id}`);

    const user1Specs = [
      { userId: user1Id, documentType: 'Tax Invoice', taxInvoiceNo: 'INV-1001', referenceNo: 'REF-501', date: '01/01/2026', uploadStatus: 'processed', edited: false, createdAtOffsetMin: 40 },
      { userId: user1Id, documentType: 'Tax Invoice', taxInvoiceNo: 'INV-2002', referenceNo: null, date: '15/02/2026', uploadStatus: 'processed', edited: true, createdAtOffsetMin: 30 },
      { userId: user1Id, documentType: 'Delivery Challan', number: 'DC-3003', date: '20/03/2026', uploadStatus: 'processed', edited: false, createdAtOffsetMin: 20 },
      { userId: user1Id, documentType: 'Delivery Challan', number: 'DC-4004', date: '05/04/2026', uploadStatus: 'failed', edited: false, createdAtOffsetMin: 10 },
      { userId: user1Id, documentType: 'Tax Invoice', taxInvoiceNo: 'INV-5005', referenceNo: 'REF-905', date: '10/05/2026', uploadStatus: 'processed', edited: true, createdAtOffsetMin: 0 },
    ];
    const insertedIds1 = seedDocs(user1Specs);
    log('setup: seeded 5 documents for user1 via pymongo', insertedIds1.length === 5, JSON.stringify(insertedIds1));

    // Log in through the real UI (not just API) so we exercise the actual app.
    await page1.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await page1.fill('input[autocomplete="email"]', email1);
    await page1.fill('input[autocomplete="current-password"]', password);
    await page1.click('button[type="submit"]');
    await page1.waitForURL(BASE + '/', { timeout: 10000 });

    // Entry point link on DocumentsPage
    await page1.goto(`${BASE}/documents`, { waitUntil: 'networkidle' });
    const hasLink = await page1.locator('a:has-text("View All Details")').count();
    log('entry point: "View All Details" link present on My Documents page', hasLink > 0, `count=${hasLink}`);
    await page1.click('a:has-text("View All Details")');
    await page1.waitForURL(/\/documents\/view-all$/, { timeout: 10000 });
    await page1.waitForTimeout(800);

    // Row count matches seeded data
    const rowCount = await page1.locator('table tbody tr').count();
    log('table renders with expected row count (5)', rowCount === 5, `rowCount=${rowCount}`);

    const bodyText1 = await page1.locator('table').innerText();

    // Number column format checks (must match backend _format_number_cell)
    const hasBothFields = /INV-1001 \/ REF-501/.test(bodyText1);
    log('Number column: Tax Invoice with both fields = "taxInvoiceNo / referenceNo"', hasBothFields);

    const onlyTaxInvoiceRowMatch = bodyText1.split('\n').find((l) => l.includes('INV-2002'));
    const noTrailingSlash = Boolean(onlyTaxInvoiceRowMatch) && !onlyTaxInvoiceRowMatch.includes('INV-2002 /') && !onlyTaxInvoiceRowMatch.includes('/ INV-2002');
    log('Number column: Tax Invoice with only taxInvoiceNo = just "taxInvoiceNo" (no trailing " / ")', noTrailingSlash, onlyTaxInvoiceRowMatch);

    const hasDC = /DC-3003/.test(bodyText1);
    log('Number column: Delivery Challan = just its "number" field', hasDC);

    // Sorting: click a column header, confirm row order changes
    const firstCellBefore = await page1.locator('table tbody tr').first().locator('td').nth(1).innerText();
    await page1.click('table thead button:has-text("Number")');
    await page1.waitForTimeout(200);
    const firstCellAfterAsc = await page1.locator('table tbody tr').first().locator('td').nth(1).innerText();
    await page1.click('table thead button:has-text("Number")');
    await page1.waitForTimeout(200);
    const firstCellAfterDesc = await page1.locator('table tbody tr').first().locator('td').nth(1).innerText();
    const sortWorks = firstCellAfterAsc !== firstCellAfterDesc;
    log('clicking a column header changes row order (sorting works)', sortWorks, `before=${firstCellBefore} asc=${firstCellAfterAsc} desc=${firstCellAfterDesc}`);

    // --- User 2: isolation check, different data, fresh browser context ---
    const email2 = `viewall2_${rand}@example.com`;
    ctx2 = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page2 = await ctx2.newPage();
    await page2.request.post(`${BASE}/api/auth/signup`, { data: { username: 'VaU2', email: email2, password } });
    const loginResp2 = await page2.request.post(`${BASE}/api/auth/login`, { data: { email: email2, password } });
    const loginJson2 = await loginResp2.json();
    const user2Id = loginJson2.user.id;

    const user2Specs = [
      { userId: user2Id, documentType: 'Delivery Challan', number: 'ONLY-USER2-DOC', date: '01/06/2026', uploadStatus: 'processed', edited: false, createdAtOffsetMin: 0 },
    ];
    const insertedIds2 = seedDocs(user2Specs);
    log('setup: seeded 1 document for user2 via pymongo', insertedIds2.length === 1, JSON.stringify(insertedIds2));

    await page2.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await page2.fill('input[autocomplete="email"]', email2);
    await page2.fill('input[autocomplete="current-password"]', password);
    await page2.click('button[type="submit"]');
    await page2.waitForURL(BASE + '/', { timeout: 10000 });
    await page2.goto(`${BASE}/documents/view-all`, { waitUntil: 'networkidle' });
    await page2.waitForTimeout(800);

    const rowCount2 = await page2.locator('table tbody tr').count();
    const bodyText2 = await page2.locator('table').innerText();
    const isolationOk = rowCount2 === 1 && bodyText2.includes('ONLY-USER2-DOC') && !bodyText2.includes('INV-1001') && !bodyText2.includes('DC-3003');
    log('isolation: user2 sees only their own 1 document, none of user1\'s data', isolationOk, `rowCount2=${rowCount2}`);

    // --- Cleanup ---
    const purge1 = await page1.request.delete(`${BASE}/api/documents/purge-all`, { headers: { Authorization: `Bearer ${loginJson1.token}` } });
    log('cleanup: purge-all for user1', purge1.ok(), `status=${purge1.status()}`);
    const purge2 = await page2.request.delete(`${BASE}/api/documents/purge-all`, { headers: { Authorization: `Bearer ${loginJson2.token}` } });
    log('cleanup: purge-all for user2', purge2.ok(), `status=${purge2.status()}`);
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
  } finally {
    if (ctx1) await ctx1.close();
    if (ctx2) await ctx2.close();
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
  const failed = results.filter((r) => !r.ok);
  if (failed.length) {
    console.log(`\n${failed.length} FAILED`);
    process.exitCode = 1;
  } else {
    console.log('\nALL PASSED');
  }
})();
