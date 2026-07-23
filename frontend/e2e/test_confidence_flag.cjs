const { chromium } = require('playwright');
const BASE = 'http://localhost:5174';
const results = [];
function log(step, ok, detail) {
  results.push({ step, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  try {
    // Find whichever account owns the low-confidence test doc - re-login as the ocrtest account
    // (created moments ago in this same verification pass)
    const email = process.argv[2];
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await page.fill('input[autocomplete="email"]', email);
    await page.fill('input[autocomplete="current-password"]', 'Test1234!');
    await page.click('button[type="submit"]');
    await page.waitForURL(BASE + '/', { timeout: 10000 });

    await page.goto(`${BASE}/documents/6a626e1ecb5ec697fe5c1b1e`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(800);

    const lowConfidenceIcon = page.locator('[aria-label="Low confidence — please verify"]');
    const highConfidenceIcon = page.locator('[aria-label="High confidence"]');
    const lowCount = await lowConfidenceIcon.count();
    const highCount = await highConfidenceIcon.count();
    log('Item 30: low-confidence field shows the red flag indicator', lowCount >= 1, `lowCount=${lowCount} highCount=${highCount}`);

    // Confirm the icon is actually visually red (not just present in DOM)
    if (lowCount >= 1) {
      const classAttr = await lowConfidenceIcon.first().getAttribute('class');
      log('Item 30: red-flag icon has red styling classes', /red/.test(classAttr || ''), classAttr);
    }

    await page.screenshot({ path: __dirname + '/shot_confidence_flag.png', fullPage: true });
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
})();
