const { chromium } = require('playwright');
const BASE = 'http://localhost:5174';
const results = [];
function log(step, ok, detail) {
  results.push({ step, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ storageState: __dirname + '/storage_state.json', viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();
  const netErrors = [];
  page.on('response', (res) => { if (res.status() >= 400) netErrors.push(`${res.status()} ${res.url()}`); });

  try {
    // Find a genuinely processed Delivery Challan document via My Documents.
    await page.goto(`${BASE}/documents?type=Delivery+Challan`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(800);
    const cards = page.locator('article');
    const count = await cards.count();
    let targetHref = null;
    for (let i = 0; i < count; i++) {
      const card = cards.nth(i);
      const isProcessed = await card.locator('text=Processed').isVisible().catch(() => false);
      if (isProcessed) {
        targetHref = await card.locator('a:has-text("View Details")').getAttribute('href');
        break;
      }
    }
    log('Found a processed Delivery Challan document to test against', Boolean(targetHref), targetHref);
    if (!targetHref) throw new Error('no processed document found');

    await page.goto(`${BASE}${targetHref}`, { waitUntil: 'networkidle' });
    const statusBadge = await page.locator('span.capitalize').innerText();
    log('Opened document is actually "processed"', statusBadge.toLowerCase() === 'processed', `status=${statusBadge}`);

    // Edit
    const editButtons = page.locator('button:has-text("Edit")');
    const editCount = await editButtons.count();
    log('Extracted fields render with Edit buttons', editCount > 0, `editCount=${editCount}`);
    if (editCount > 0) {
      await editButtons.first().click();
      const dialogVisible = await page.locator('text=Edit Field Value').isVisible().catch(() => false);
      log('Edit opens a styled dialog (not native prompt)', dialogVisible);
      if (dialogVisible) {
        await page.fill('input[placeholder="Enter corrected value"]', 'TESTVALUE123');
        await page.click('button:has-text("Save Correction")');
        const toastVisible = await page.waitForSelector('text=updated successfully', { timeout: 6000 }).then(() => true).catch(() => false);
        log('Field edit shows a success toast', toastVisible);
        await page.waitForTimeout(500);
        const fieldUpdated = await page.locator('text=TESTVALUE123').isVisible().catch(() => false);
        log('Edited field value reflects on the page', fieldUpdated);
      }
    }

    // Save to Excel
    const saveBtn = page.locator('button:has-text("Save to Excel")');
    const saveBtnVisible = await saveBtn.isVisible().catch(() => false);
    log('Save to Excel button visible on a processed document', saveBtnVisible);
    if (saveBtnVisible) {
      await saveBtn.click();
      await page.waitForTimeout(2000);
      const anyToast = await page.locator('[data-sonner-toast]').count();
      const anyDialog = await page.locator('text=New workbook needed').isVisible().catch(() => false);
      log('Save to Excel gives clear feedback (toast or workbook-name dialog)', anyToast > 0 || anyDialog, `toastCount=${anyToast} promptDialog=${anyDialog}`);
      if (anyDialog) {
        // Cancel the prompt to avoid mutating workbook state unexpectedly during this check
        await page.click('button:has-text("Cancel")');
      }
    }

    // Download original
    const downloadPromise = page.waitForEvent('download', { timeout: 10000 }).catch(() => null);
    await page.click('button:has-text("Download Original")');
    const download = await downloadPromise;
    log('Download Original downloads a file (authenticated, no 401)', Boolean(download), download ? `filename=${download.suggestedFilename()}` : 'no download event');

    log('No 4xx/5xx network responses during detail-page checks', netErrors.length === 0, netErrors.join(' | '));

    await page.screenshot({ path: __dirname + '/shot_detail_focused.png', fullPage: true });
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
    await page.screenshot({ path: __dirname + '/shot_error_detail_focused.png', fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
})();
