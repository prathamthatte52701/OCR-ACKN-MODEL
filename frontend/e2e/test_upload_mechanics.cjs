const { chromium } = require('playwright');
const BASE = 'http://localhost:5174';
const SCRATCH = 'C:\\Users\\Pratham\\AppData\\Local\\Temp\\claude\\E--Python-OCR-ACKN-Model\\73cbf230-50d6-4e37-b132-c7170a38c178\\scratchpad';
const results = [];
function log(step, ok, detail) {
  results.push({ step, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`);
}

const rand = Math.floor(Math.random() * 1000000);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();

  try {
    const email = `uploadmech_${rand}@example.com`;
    await page.request.post(`${BASE}/api/auth/signup`, { data: { username: 'UpMech1', email, password: 'Test1234!' } });
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await page.fill('input[autocomplete="email"]', email);
    await page.fill('input[autocomplete="current-password"]', 'Test1234!');
    await page.click('button[type="submit"]');
    await page.waitForURL(BASE + '/', { timeout: 10000 });

    // ===== Item 18: single upload accepts one file with documentType selection =====
    await page.goto(`${BASE}/upload`, { waitUntil: 'networkidle' });
    await page.click('button:has-text("Single Upload")');
    await page.click('button:has-text("Delivery Challan")');
    await page.locator('input[type="file"]').first().setInputFiles('E:\\test doc\\1-D.pdf');
    await page.waitForSelector('button:has-text("Upload & Process")', { timeout: 5000 });
    await page.click('button:has-text("Upload & Process")');
    const acceptedUploading = await page.waitForSelector('text=Uploading document...', { timeout: 5000 }).then(() => true).catch(() => false);
    const acceptedProcessing = acceptedUploading || await page.waitForSelector('text=Running OCR', { timeout: 10000 }).then(() => true).catch(() => false);
    log('Item 18: single upload with file + documentType accepted and starts processing', acceptedProcessing);

    // ===== Item 20: file size limit (5MB) with clear message =====
    await page.goto(`${BASE}/upload`, { waitUntil: 'networkidle' });
    await page.click('button:has-text("Single Upload")');
    await page.locator('input[type="file"]').first().setInputFiles(SCRATCH + '\\oversized.pdf');
    await page.waitForTimeout(500);
    const sizeErrorText = await page.locator('body').innerText();
    const sizeErrorShown = /5\s*MB/i.test(sizeErrorText) && !(await page.locator('button:has-text("Upload & Process")').isVisible().catch(() => false));
    log('Item 20: oversized file (6MB) rejected client-side with clear 5MB message', /5\s*MB or less/i.test(sizeErrorText), sizeErrorText.match(/File size must be[^.]*\./)?.[0] || 'no matching message found');

    // ===== Item 21: file type restriction with clear message =====
    await page.goto(`${BASE}/upload`, { waitUntil: 'networkidle' });
    await page.click('button:has-text("Single Upload")');
    await page.locator('input[type="file"]').first().setInputFiles(SCRATCH + '\\unsupported.txt');
    await page.waitForTimeout(500);
    const typeErrorText = await page.locator('body').innerText();
    log('Item 21: unsupported file type (.txt) rejected with clear message', /Only JPG, JPEG, PNG, and PDF/i.test(typeErrorText), typeErrorText.match(/Only JPG[^.]*\./)?.[0] || 'no matching message found');

    // ===== Item 19 + 22: bulk upload sequential + View All Results with pagination =====
    await page.goto(`${BASE}/upload`, { waitUntil: 'networkidle' });
    await page.click('button:has-text("Bulk Upload")');
    const bulkFiles = ['E:\\test doc\\2-D.pdf', 'E:\\test doc\\3-D.pdf', 'E:\\test doc\\4-D.pdf'];
    await page.locator('input[type="file"][multiple]').setInputFiles(bulkFiles);
    await page.waitForTimeout(500);
    const dropdowns = page.locator('select');
    const ddCount = await dropdowns.count();
    for (let i = 0; i < ddCount; i++) {
      await dropdowns.nth(i).selectOption('Delivery Challan');
    }
    const bulkStartTime = Date.now();
    await page.click(`button:has-text("Upload All (${bulkFiles.length})")`);
    await page.waitForSelector('text=View All Results', { timeout: 240000 });
    const bulkDuration = Date.now() - bulkStartTime;
    log('Item 22: "View All Results" screen appears after bulk upload', true, `took ${Math.round(bulkDuration / 1000)}s for 3 files`);

    const bodyText = await page.locator('body').innerText();
    const summaryMatch = bodyText.match(/(\d+)\/(\d+) processed/);
    log('Item 22: results screen shows outcome summary for all files', Boolean(summaryMatch) && summaryMatch[2] === '3', summaryMatch?.[0]);

    const rows = await page.locator('a:has-text("Review"), text=Failed').count();
    log('Item 22: each of the 3 files has a visible outcome row', rows >= 3, `outcomeRows=${rows}`);

    // Pagination controls structurally can't appear with <=5 results (MAX_BULK_FILES == RESULTS_PAGE_SIZE == 5)
    const paginationVisible = await page.locator('text=Page 1 of').isVisible().catch(() => false);
    log('Item 22 note: pagination controls correctly absent for <=5 results (1 page)', !paginationVisible, `visible=${paginationVisible}`);

    await page.screenshot({ path: __dirname + '/shot_upload_mech_bulk_results.png', fullPage: true });
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
    await page.screenshot({ path: __dirname + '/shot_upload_mech_error.png', fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
})();
