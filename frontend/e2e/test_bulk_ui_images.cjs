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
    const email = `bulkuiimg_${rand}@example.com`;
    await page.request.post(`${BASE}/api/auth/signup`, { data: { username: 'BulkImg1', email, password: 'Test1234!' } });
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await page.fill('input[autocomplete="email"]', email);
    await page.fill('input[autocomplete="current-password"]', 'Test1234!');
    await page.click('button[type="submit"]');
    await page.waitForURL(BASE + '/', { timeout: 10000 });

    await page.goto(`${BASE}/upload`, { waitUntil: 'networkidle' });
    await page.click('button:has-text("Bulk Upload")');
    const files = [
      'E:\\test doc\\WhatsApp Image 2026-07-23 at 23.58.51 (3).jpeg',
      'E:\\test doc\\WhatsApp Image 2026-07-23 at 23.58.51 (4).jpeg',
      'E:\\test doc\\WhatsApp Image 2026-07-23 at 23.58.51 (5).jpeg',
      'E:\\test doc\\WhatsApp Image 2026-07-23 at 23.58.51 (6).jpeg',
      'E:\\test doc\\WhatsApp Image 2026-07-23 at 23.58.51 (7).jpeg',
    ];
    await page.locator('input[type="file"][multiple]').setInputFiles(files);
    await page.waitForTimeout(500);
    const dropdowns = page.locator('select');
    const ddCount = await dropdowns.count();
    for (let i = 0; i < ddCount; i++) {
      await dropdowns.nth(i).selectOption('Delivery Challan');
    }

    const start = Date.now();
    await page.click(`button:has-text("Upload All (${files.length})")`);
    await page.waitForSelector('text=View All Results', { timeout: 600000 });
    const elapsed = (Date.now() - start) / 1000;

    const bodyText = await page.locator('body').innerText();
    const summaryMatch = bodyText.match(/(\d+)\/(\d+) processed/);
    log('Bulk 5-file IMAGE batch settles', Boolean(summaryMatch), `took ${elapsed.toFixed(1)}s`);
    log('Frontend shows all 5 as processed (not false-failed)', summaryMatch && summaryMatch[1] === '5' && summaryMatch[2] === '5', summaryMatch?.[0]);

    await page.screenshot({ path: __dirname + '/shot_bulk_images_after_fix.png', fullPage: true });
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
    await page.screenshot({ path: __dirname + '/shot_bulk_images_error.png', fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
})();
