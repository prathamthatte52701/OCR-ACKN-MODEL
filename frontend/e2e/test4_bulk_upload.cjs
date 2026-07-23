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
  const consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push('pageerror: ' + err.message));

  try {
    await page.goto(`${BASE}/upload`, { waitUntil: 'networkidle' });
    await page.click('button:has-text("Bulk Upload")');

    const filePaths = ['E:\\test doc\\2-D.pdf', 'E:\\test doc\\3-D.pdf', 'E:\\test doc\\4-D.pdf'];
    const fileInput = page.locator('input[type="file"][multiple]');
    await fileInput.setInputFiles(filePaths);
    await page.waitForTimeout(500);

    const rowCount = await page.locator('select').count();
    log('Per-file document-type dropdowns appear (one per file)', rowCount === filePaths.length, `count=${rowCount}`);

    // Every bulk file defaults to "Tax Invoice" (matches the old app's own
    // default - the user is expected to correct each dropdown). These are
    // Delivery Challan samples, so set every dropdown correctly before upload.
    for (let i = 0; i < rowCount; i++) {
      await page.locator('select').nth(i).selectOption('Delivery Challan');
    }
    const selected = await page.locator('select').first().inputValue();
    log('Per-file dropdown is changeable', selected === 'Delivery Challan', `selected=${selected}`);

    await page.click(`button:has-text("Upload All (${filePaths.length})")`);

    const sawStatusChips = await page.waitForSelector('text=/Waiting|Processing|Done|Failed/', { timeout: 10000 }).then(() => true).catch(() => false);
    log('Live per-file status chips appear during bulk processing', sawStatusChips);

    await page.screenshot({ path: __dirname + '/shot_bulk_processing.png', fullPage: true }).catch(() => {});

    const resultsScreen = await page.waitForSelector('text=View All Results', { timeout: 240000 }).then(() => true).catch(() => false);
    log('"View All Results" screen appears once all files settle', resultsScreen);

    if (resultsScreen) {
      const bodyText = await page.locator('body').innerText();
      const summaryMatch = bodyText.match(/(\d+)\/(\d+) processed/);
      log('Results summary shows done/total count', Boolean(summaryMatch), summaryMatch ? summaryMatch[0] : 'not found');

      const reviewLinks = await page.locator('a:has-text("Review")').count();
      const failedBadges = await page.locator('text=Failed').count();
      log('Each result row shows a Review link or Failed badge', reviewLinks + failedBadges === filePaths.length, `review=${reviewLinks} failed=${failedBadges} total=${filePaths.length}`);

      await page.screenshot({ path: __dirname + '/shot_bulk_results.png', fullPage: true });
    } else {
      await page.screenshot({ path: __dirname + '/shot_bulk_timeout.png', fullPage: true }).catch(() => {});
    }

    log('No console errors during bulk upload flow', consoleErrors.length === 0, consoleErrors.slice(0, 5).join(' | '));
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
    await page.screenshot({ path: __dirname + '/shot_error_bulk.png', fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
})();
