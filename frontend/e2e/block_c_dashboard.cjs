const { chromium } = require('playwright');
const BASE = 'http://localhost:5174';
const results = [];
function log(step, ok, detail) {
  results.push({ step, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`);
}
const rand = Math.floor(Math.random() * 1000000);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  try {
    const email = `blockc_${rand}@example.com`;
    await page.request.post(`${BASE}/api/auth/signup`, { data: { username: 'BlockC', email, password: 'Test1234!' } });
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await page.fill('input[autocomplete="email"]', email);
    await page.fill('input[autocomplete="current-password"]', 'Test1234!');
    await page.click('button[type="submit"]');
    await page.waitForURL(BASE + '/', { timeout: 10000 });

    // upload one Delivery Challan doc via API so dashboard has real data
    const loginResp = await page.request.post(`${BASE}/api/auth/login`, { data: { email, password: 'Test1234!' } });
    const { token } = await loginResp.json();
    const fs = require('fs');
    const buf = fs.readFileSync('E:\\test doc\\1-D.pdf');
    const uploadResp = await page.request.post(`${BASE}/api/documents/upload`, {
      headers: { Authorization: `Bearer ${token}` },
      multipart: { document: { name: '1-D.pdf', mimeType: 'application/pdf', buffer: buf }, documentType: 'Delivery Challan' },
    });
    const uploadJson = await uploadResp.json();
    const docId = uploadJson.document._id;
    let status = 'uploaded';
    const deadline = Date.now() + 600000;
    while (Date.now() < deadline && status !== 'processed' && status !== 'failed') {
      await page.waitForTimeout(3000);
      const r = await page.request.get(`${BASE}/api/documents/${docId}`, { headers: { Authorization: `Bearer ${token}` } });
      const j = await r.json();
      status = j.document.uploadStatus;
    }
    log('setup: doc processed for dashboard test', status === 'processed', `status=${status}`);

    // Item 44/45: dashboard stat cards
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    const bodyText = await page.locator('body').innerText();
    const hasTotal = /Total Documents/.test(bodyText);
    const hasProcessed = /\bProcessed\b/.test(bodyText);
    const hasFailed = /\bFailed\b/.test(bodyText);
    const hasToday = /Processed Today/.test(bodyText);
    const hasTaxInvoiceCard = /Tax Invoice/.test(bodyText);
    const hasDCCard = /Delivery Challan/.test(bodyText);
    log('Item 44: stat cards present (Total/Processed/Failed/Processed Today)', hasTotal && hasProcessed && hasFailed && hasToday);
    log('Item 45: Tax Invoice and Delivery Challan shown as separate individual cards', hasTaxInvoiceCard && hasDCCard);

    // Item 46/47: search bar - button triggered, not live
    await page.fill('input[placeholder="e.g. 820268362"]', '820268362');
    await page.waitForTimeout(600);
    const urlBeforeClick = page.url();
    log('Item 46: typing in search box does NOT navigate (not live search)', urlBeforeClick === `${BASE}/`, `url=${urlBeforeClick}`);

    await page.click('button:has-text("Search")');
    await page.waitForURL(/\/documents\?number=820268362/, { timeout: 5000 });
    log('Item 47: clicking Search navigates to My Documents filtered by number', page.url().includes('number=820268362'), `url=${page.url()}`);

    await page.waitForTimeout(800);
    const resultsText = await page.locator('body').innerText();
    log('Item 47b: filtered results page shows the filter applied', /Filtered by/.test(resultsText), resultsText.slice(0, 100));

  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
})();
