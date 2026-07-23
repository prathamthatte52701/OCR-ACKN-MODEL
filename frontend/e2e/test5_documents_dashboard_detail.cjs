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
    // -- My Documents --
    await page.goto(`${BASE}/documents`, { waitUntil: 'networkidle' });
    const hasTabs = await page.locator('button:has-text("Tax Invoice")').isVisible() && await page.locator('button:has-text("Delivery Challan")').isVisible();
    log('My Documents shows Tax Invoice / Delivery Challan tabs', hasTabs);

    await page.click('button:has-text("Delivery Challan")');
    await page.waitForTimeout(1000);
    const dcCards = await page.locator('h3').count();
    log('Delivery Challan tab shows documents', dcCards > 0, `count=${dcCards}`);

    // Search test
    const bodyBefore = await page.locator('body').innerText();
    const numberMatch = bodyBefore.match(/Number:\s*([\d]+)/);
    if (numberMatch) {
      const partial = numberMatch[1].slice(0, 5);
      await page.goto(`${BASE}/documents?type=Delivery+Challan&number=${partial}`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(800);
      const filtered = await page.locator('text=Filtered by').isVisible().catch(() => false);
      log('Search by partial number filters and shows "Filtered by"', filtered, `searched=${partial}`);
      await page.click('text=Clear Search');
      await page.waitForTimeout(500);
      log('Clear Search removes the filter', page.url().includes('number=') === false, `url=${page.url()}`);
    } else {
      log('Search by partial number filters', false, 'no number found in list to search with');
    }

    await page.screenshot({ path: __dirname + '/shot_documents_page.png', fullPage: true });

    // -- Dashboard --
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    const statLabels = ['Total Documents', 'Processed', 'Failed', 'Processed Today', 'Tax Invoice', 'Delivery Challan'];
    let allStatsPresent = true;
    for (const label of statLabels) {
      const present = await page.locator(`text=${label}`).first().isVisible().catch(() => false);
      if (!present) allStatsPresent = false;
    }
    log('All 6 stat cards render', allStatsPresent);

    const totalDocsText = await page.locator('text=Acknowledgements in workspace').locator('..').innerText().catch(() => '');
    log('Stat cards show numeric values (spot check)', /\d/.test(totalDocsText), totalDocsText.replace(/\n/g, ' | '));

    await page.screenshot({ path: __dirname + '/shot_dashboard.png', fullPage: true });

    // Dashboard search bar -> redirect to My Documents with query
    await page.fill('input[placeholder="e.g. 820268362"]', '82026');
    await page.click('button:has-text("Search")');
    await page.waitForURL(/\/documents\?/, { timeout: 5000 }).catch(() => {});
    log('Dashboard search bar redirects to /documents with number param', page.url().includes('number=82026'), `url=${page.url()}`);

    // -- Document Detail --
    await page.goto(`${BASE}/documents?type=Delivery+Challan`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(800);
    const viewDetailsLink = page.locator('a:has-text("View Details")').first();
    const hasLink = await viewDetailsLink.isVisible().catch(() => false);
    if (hasLink) {
      await viewDetailsLink.click();
      await page.waitForURL(/\/documents\/[a-f0-9]{24}$/, { timeout: 10000 });

      // Edit a field
      const editButtons = page.locator('button:has-text("Edit")');
      const editCount = await editButtons.count();
      if (editCount > 0) {
        await editButtons.first().click();
        const dialogVisible = await page.locator('text=Edit Field Value').isVisible().catch(() => false);
        log('Edit opens a styled dialog (not native prompt)', dialogVisible);
        if (dialogVisible) {
          const input = page.locator('input[placeholder="Enter corrected value"]');
          await input.fill('TESTVALUE123');
          await page.click('button:has-text("Save Correction")');
          const toastVisible = await page.waitForSelector('text=updated successfully', { timeout: 6000 }).then(() => true).catch(() => false);
          log('Field edit shows a success toast', toastVisible);
          await page.waitForTimeout(500);
          const fieldUpdated = await page.locator('text=TESTVALUE123').isVisible().catch(() => false);
          log('Edited field value reflects on the page', fieldUpdated);
        }
      } else {
        log('Edit opens a styled dialog (not native prompt)', false, 'no Edit buttons found - document may not be processed');
      }

      // Reprocess - confirm dialog appears (not native confirm)
      let dialogHandled = false;
      page.once('dialog', (d) => { dialogHandled = true; d.dismiss(); });
      await page.click('button:has-text("Reprocess")');
      await page.waitForTimeout(500);
      const styledConfirmVisible = await page.locator('text=Reprocess this document?').isVisible().catch(() => false);
      log('Reprocess shows styled confirm dialog, not native confirm()', styledConfirmVisible && !dialogHandled, `styled=${styledConfirmVisible} nativeDialogFired=${dialogHandled}`);
      if (styledConfirmVisible) {
        await page.click('button:has-text("Yes, Reprocess")');
        const reprocessMsg = await page.waitForSelector('text=Reprocessing started', { timeout: 8000 }).then(() => true).catch(() => false);
        log('Reprocess confirm triggers and shows status message', reprocessMsg);
        // wait for it to finish reprocessing before continuing
        await page.waitForSelector('text=Reprocessing with OCR', { state: 'detached', timeout: 60000 }).catch(() => {});
      }

      // Save to Excel - some feedback (toast) either way
      await page.waitForTimeout(1000);
      const saveBtn = page.locator('button:has-text("Save to Excel")');
      if (await saveBtn.isVisible().catch(() => false)) {
        await saveBtn.click();
        const anyToast = await page.waitForSelector('[data-sonner-toast]', { timeout: 8000 }).then(() => true).catch(() => false);
        log('Save to Excel gives clear toast feedback', anyToast);
      } else {
        log('Save to Excel gives clear toast feedback', false, 'Save button not visible (doc not processed?)');
      }

      // Download original
      const downloadPromise = page.waitForEvent('download', { timeout: 10000 }).catch(() => null);
      await page.click('button:has-text("Download Original")');
      const download = await downloadPromise;
      log('Download Original actually downloads a file (authenticated, no 401)', Boolean(download), download ? `filename=${download.suggestedFilename()}` : 'no download event fired');

      await page.screenshot({ path: __dirname + '/shot_document_detail.png', fullPage: true });
    } else {
      log('Document detail flow', false, 'no processed Delivery Challan document with View Details link found');
    }

    // -- Mobile viewport --
    await page.setViewportSize({ width: 390, height: 844 });
    for (const [name, url] of [['Dashboard', '/'], ['Upload', '/upload'], ['My Documents', '/documents']]) {
      await page.goto(`${BASE}${url}`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(500);
      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
      const overflows = scrollWidth > clientWidth + 2;
      log(`${name} has no horizontal overflow at 390px width`, !overflows, `scrollWidth=${scrollWidth} clientWidth=${clientWidth}`);
      await page.screenshot({ path: __dirname + `/shot_mobile_${name.replace(/\s+/g, '_')}.png`, fullPage: true });
    }
    // Hamburger menu
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    const hamburger = page.locator('button[aria-label="Toggle menu"]');
    await hamburger.click();
    await page.waitForTimeout(300);
    const mobileNavVisible = await page.locator('text=My Documents').last().isVisible().catch(() => false);
    log('Mobile hamburger menu opens and shows nav links', mobileNavVisible);
    await page.screenshot({ path: __dirname + '/shot_mobile_menu_open.png', fullPage: true });

    log('No console errors across documents/dashboard/detail/mobile checks', consoleErrors.length === 0, consoleErrors.slice(0, 8).join(' | '));
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
    await page.screenshot({ path: __dirname + '/shot_error_docs_dash.png', fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
})();
