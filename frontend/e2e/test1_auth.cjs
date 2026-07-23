const { chromium } = require('playwright');

const BASE = 'http://localhost:5174';
const results = [];
function log(step, ok, detail) {
  results.push({ step, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`);
}

const rand = Math.floor(Math.random() * 100000);
const USERNAME = `tester${rand}`.slice(0, 8);
const EMAIL = `tester${rand}@example.com`;
const PASSWORD = 'Test1234!';
const NEW_PASSWORD = 'Test5678!';
const FINAL_PASSWORD = 'Test9999!';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push('pageerror: ' + err.message));

  try {
    // Signup
    await page.goto(`${BASE}/signup`, { waitUntil: 'networkidle' });
    await page.fill('input[autocomplete="username"]', USERNAME);
    await page.fill('input[autocomplete="email"]', EMAIL);
    await page.fill('input[autocomplete="new-password"]', PASSWORD);
    await page.click('button[type="submit"]');
    await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
    const successBanner = await page.waitForSelector('text=Account created', { timeout: 5000 }).then(() => true).catch(() => false);
    log('Signup redirects to /login with success message', page.url().includes('/login') && successBanner, `url=${page.url()} banner=${successBanner}`);

    // Login
    await page.fill('input[autocomplete="email"]', EMAIL);
    await page.fill('input[autocomplete="current-password"]', PASSWORD);
    // Eye icon toggle test before submit
    const pwInput = page.locator('input[autocomplete="current-password"]');
    const typeBefore = await pwInput.getAttribute('type');
    await page.locator('button[aria-label="Show password"]').click();
    const typeAfter = await pwInput.getAttribute('type');
    log('Password eye-icon toggle works', typeBefore === 'password' && typeAfter === 'text', `before=${typeBefore} after=${typeAfter}`);
    await page.locator('button[aria-label="Hide password"]').click();

    await page.click('button[type="submit"]');
    await page.waitForURL(BASE + '/', { timeout: 10000 });
    log('Login redirects to Dashboard', page.url() === BASE + '/', `url=${page.url()}`);

    await page.screenshot({ path: 'E:/Python OCR ACKN Model/frontend/e2e/'+'shot_dashboard_after_login.png', fullPage: true });

    // Logout
    await page.click('text=Log out');
    await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
    log('Logout returns to /login', page.url().includes('/login'));

    // Log back in
    await page.fill('input[autocomplete="email"]', EMAIL);
    await page.fill('input[autocomplete="current-password"]', PASSWORD);
    await page.click('button[type="submit"]');
    await page.waitForURL(BASE + '/', { timeout: 10000 });
    log('Re-login after logout works', page.url() === BASE + '/');

    // Profile - edit
    await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle' });
    await page.click('text=Edit');
    const newUsername = USERNAME.slice(0, 7) + 'x';
    await page.fill('form input[minlength="3"]', newUsername);
    await page.click('button:has-text("Save changes")');
    await page.waitForSelector('text=Profile updated.', { timeout: 8000 }).catch(() => {});
    const profileUpdated = await page.locator('text=Profile updated.').isVisible().catch(() => false);
    log('Profile edit saves and shows success message', profileUpdated);

    // Change password
    await page.fill('input[autocomplete="current-password"]', PASSWORD);
    const newPwFields = page.locator('input[autocomplete="new-password"]');
    await newPwFields.nth(0).fill(NEW_PASSWORD);
    await newPwFields.nth(1).fill(NEW_PASSWORD);
    await page.click('button:has-text("Change password")');
    await page.waitForSelector('text=Password changed', { timeout: 8000 }).catch(() => {});
    const pwChanged = await page.locator('text=Password changed').isVisible().catch(() => false);
    log('Change password succeeds with success message', pwChanged);

    // Logout and re-login with new password to confirm it took effect.
    // Navigate to Dashboard first so the post-login "return to previous
    // page" redirect (RequireAuth's ?next=) lands on / for a clean check,
    // rather than back on /profile (also correct, just not what this
    // assertion is isolating).
    await page.goto(BASE + '/', { waitUntil: 'networkidle' });
    await page.click('text=Log out');
    await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
    await page.fill('input[autocomplete="email"]', EMAIL);
    await page.fill('input[autocomplete="current-password"]', NEW_PASSWORD);
    await page.click('button[type="submit"]');
    await page.waitForURL(BASE + '/', { timeout: 10000 });
    log('Login with new (changed) password works', page.url() === BASE + '/');

    await page.click('text=Log out');
    await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });

    // Forgot password flow
    await page.goto(`${BASE}/forgot-password`, { waitUntil: 'networkidle' });
    await page.fill('input[type="text"]', newUsername);
    await page.fill('input[type="email"]', EMAIL);
    await page.click('button:has-text("Verify")');
    await page.waitForSelector('text=Set new password', { timeout: 8000 }).catch(() => {});
    const verifiedStep = await page.locator('text=Set new password').isVisible().catch(() => false);
    log('Forgot-password verify step succeeds', verifiedStep);

    if (verifiedStep) {
      const resetPwFields = page.locator('input[autocomplete="new-password"]');
      await resetPwFields.nth(0).fill(FINAL_PASSWORD);
      await resetPwFields.nth(1).fill(FINAL_PASSWORD);
      await page.click('button:has-text("Update password")');
      await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
      const resetSuccess = await page.waitForSelector('text=Password updated successfully', { timeout: 5000 }).then(() => true).catch(() => false);
      log('Forgot-password reset redirects to /login with success message', page.url().includes('/login') && resetSuccess);

      await page.fill('input[autocomplete="email"]', EMAIL);
      await page.fill('input[autocomplete="current-password"]', FINAL_PASSWORD);
      await page.click('button[type="submit"]');
      await page.waitForURL(BASE + '/', { timeout: 10000 });
      log('Login with password-reset password works', page.url() === BASE + '/');
    }

    log('No console errors during auth flow', consoleErrors.length === 0, consoleErrors.slice(0, 5).join(' | '));

    // Save credentials for next test scripts
    require('fs').writeFileSync('E:/Python OCR ACKN Model/frontend/e2e/'+'test_creds.json', JSON.stringify({ email: EMAIL, password: FINAL_PASSWORD, username: newUsername }));
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
    await page.screenshot({ path: 'E:/Python OCR ACKN Model/frontend/e2e/'+'shot_error_auth.png', fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
  const failed = results.filter((r) => !r.ok);
  process.exit(failed.length ? 1 : 0);
})();
