const { chromium } = require('playwright');
const BASE = 'http://localhost:5174';
const results = [];
function log(step, ok, detail) {
  results.push({ step, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ storageState: __dirname + '/storage_state.json' });
  const page = await context.newPage();

  try {
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(6000); // backend is stopped externally right before this runs
    const overlayVisible = await page.locator('text=Server is currently unreachable').isVisible().catch(() => false);
    log('Server-down overlay appears when backend is unreachable', overlayVisible);
    await page.screenshot({ path: __dirname + '/shot_server_down.png', fullPage: true });
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
})();
