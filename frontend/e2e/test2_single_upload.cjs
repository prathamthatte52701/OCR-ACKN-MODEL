const { chromium } = require('playwright');
const path = require('path');
const BASE = 'http://localhost:5174';
const results = [];
function log(step, ok, detail) {
  results.push({ step, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`);
}

async function testUpload(page, { label, docType, filePath }) {
  await page.goto(`${BASE}/upload`, { waitUntil: 'networkidle' });
  await page.click('button:has-text("Single Upload")');
  await page.click(`button:has-text("${docType}")`);

  const fileInput = page.locator('input[type="file"]').first();
  await fileInput.setInputFiles(filePath);
  await page.waitForSelector('button:has-text("Upload & Process")', { timeout: 5000 });
  await page.click('button:has-text("Upload & Process")');

  // Watch progress states
  const sawUploading = await page.waitForSelector('text=Uploading document...', { timeout: 5000 }).then(() => true).catch(() => false);
  const sawProcessing = await page.waitForSelector('text=Running OCR', { timeout: 15000 }).then(() => true).catch(() => false);
  log(`${label}: progress states shown (uploading and/or processing)`, sawUploading || sawProcessing, `uploading=${sawUploading} processing=${sawProcessing}`);

  // Wait for redirect to document detail page (up to 3 minutes per app's own timeout budget)
  const redirected = await page.waitForURL(/\/documents\/[a-f0-9]{24}$/, { timeout: 180000 }).then(() => true).catch(() => false);
  log(`${label}: redirects to document detail page after processing`, redirected, `url=${page.url()}`);

  if (!redirected) {
    await page.screenshot({ path: __dirname + `/shot_${label.replace(/\s+/g, '_')}_timeout.png`, fullPage: true }).catch(() => {});
    return;
  }

  await page.waitForTimeout(500);
  const bodyText = await page.locator('body').innerText();
  const hasProcessedFields = /TAX INVOICE No\.|Delivery Challan No\./.test(bodyText);
  log(`${label}: extracted field labels visible`, hasProcessedFields);

  const confidenceIcons = await page.locator('[aria-label="High confidence"], [aria-label="Low confidence — please verify"]').count();
  log(`${label}: confidence indicators shown per field`, confidenceIcons > 0, `count=${confidenceIcons}`);

  await page.screenshot({ path: __dirname + `/shot_${label.replace(/\s+/g, '_')}_detail.png`, fullPage: true });

  const statusBadge = await page.locator('text=/uploaded|processed|failed/i').first().innerText().catch(() => 'unknown');
  log(`${label}: final status`, true, `status=${statusBadge}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ storageState: __dirname + '/storage_state.json', viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push('pageerror: ' + err.message));

  try {
    await testUpload(page, {
      label: 'Delivery Challan upload',
      docType: 'Delivery Challan',
      filePath: 'E:\\test doc\\1-D.pdf',
    });

    await testUpload(page, {
      label: 'Tax Invoice upload',
      docType: 'Tax Invoice',
      filePath: 'E:\\testing doc\\1-T.pdf',
    });

    log('No console errors during single-upload flows', consoleErrors.length === 0, consoleErrors.slice(0, 5).join(' | '));
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
    await page.screenshot({ path: __dirname + '/shot_error_upload.png', fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
})();
