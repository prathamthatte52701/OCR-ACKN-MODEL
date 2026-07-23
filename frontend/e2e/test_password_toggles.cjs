const { chromium } = require('playwright');
const BASE = 'http://localhost:5174';
const results = [];
function log(step, ok, detail) {
  results.push({ step, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`);
}

async function checkToggle(page, selector, label) {
  const input = page.locator(selector).first();
  const before = await input.getAttribute('type');
  const toggleBtn = input.locator('xpath=following-sibling::button[1]');
  const btnCount = await toggleBtn.count();
  if (btnCount === 0) {
    log(`${label}: eye-icon toggle button present`, false, 'no sibling button found');
    return;
  }
  await toggleBtn.click();
  const after = await input.getAttribute('type');
  log(`${label}: eye-icon toggle actually switches type`, before === 'password' && after === 'text', `before=${before} after=${after}`);
  await toggleBtn.click();
  const restored = await input.getAttribute('type');
  log(`${label}: toggle switches back to hidden`, restored === 'password', `restored=${restored}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();

  try {
    // Login page
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await checkToggle(page, 'input[autocomplete="current-password"]', 'Login page password field');

    // Signup page
    await page.goto(`${BASE}/signup`, { waitUntil: 'networkidle' });
    await checkToggle(page, 'input[autocomplete="new-password"]', 'Signup page password field');

    // Forgot password page - step 2 (new password fields) requires verify step first
    const rand = Math.floor(Math.random() * 1000000);
    const email = `toggletest_${rand}@example.com`;
    const username = 'ToggleU';
    await page.request.post(`${BASE}/api/auth/signup`, { data: { username, email, password: 'Test1234!' } });
    await page.goto(`${BASE}/forgot-password`, { waitUntil: 'networkidle' });
    await page.fill('input[type="text"]', username);
    await page.fill('input[type="email"]', email);
    await page.click('button:has-text("Verify")');
    await page.waitForSelector('text=Set new password', { timeout: 8000 });
    const newPwFields = page.locator('input[autocomplete="new-password"]');
    const npCount = await newPwFields.count();
    log('Forgot-password reset step: has 2 password fields', npCount === 2, `count=${npCount}`);
    if (npCount === 2) {
      const first = newPwFields.nth(0);
      const firstBefore = await first.getAttribute('type');
      const firstToggle = first.locator('xpath=following-sibling::button[1]');
      await firstToggle.click();
      const firstAfter = await first.getAttribute('type');
      log('Forgot-password: new-password field toggle works', firstBefore === 'password' && firstAfter === 'text', `before=${firstBefore} after=${firstAfter}`);

      const second = newPwFields.nth(1);
      const secondBefore = await second.getAttribute('type');
      const secondToggle = second.locator('xpath=following-sibling::button[1]');
      await secondToggle.click();
      const secondAfter = await second.getAttribute('type');
      log('Forgot-password: confirm-password field toggle works', secondBefore === 'password' && secondAfter === 'text', `before=${secondBefore} after=${secondAfter}`);
    }

    // Login as this user, go to Profile -> Change Password panel (3 password fields)
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    // password was just reset via forgot-password flow above to whatever was typed - re-signup a fresh known-password account instead for reliability
    const rand2 = Math.floor(Math.random() * 1000000);
    const email2 = `toggletest2_${rand2}@example.com`;
    await page.request.post(`${BASE}/api/auth/signup`, { data: { username: 'ToggleU2', email: email2, password: 'Test1234!' } });
    await page.fill('input[autocomplete="email"]', email2);
    await page.fill('input[autocomplete="current-password"]', 'Test1234!');
    await page.click('button[type="submit"]');
    await page.waitForURL(BASE + '/', { timeout: 10000 });

    await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle' });
    const profilePwFields = page.locator('input[autocomplete="current-password"], input[autocomplete="new-password"]');
    const profileCount = await profilePwFields.count();
    log('Profile Change Password panel: has 3 password fields', profileCount === 3, `count=${profileCount}`);
    for (let i = 0; i < profileCount; i++) {
      const field = profilePwFields.nth(i);
      const before = await field.getAttribute('type');
      const toggle = field.locator('xpath=following-sibling::button[1]');
      await toggle.click();
      const after = await field.getAttribute('type');
      log(`Profile password field ${i}: toggle works`, before === 'password' && after === 'text', `before=${before} after=${after}`);
    }

    await page.screenshot({ path: __dirname + '/shot_toggle_profile.png', fullPage: true });
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
    await page.screenshot({ path: __dirname + '/shot_toggle_error.png', fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
})();
