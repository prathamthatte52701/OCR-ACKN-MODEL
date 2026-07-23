const { chromium } = require('playwright');
const BASE = 'http://localhost:5174';
const results = [];
function log(step, ok, detail) {
  results.push({ step, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`);
}

const rand = Math.floor(Math.random() * 1000000);

async function doSignup(page, { username, email, password }) {
  await page.goto(`${BASE}/signup`, { waitUntil: 'networkidle' });
  await page.fill('input[autocomplete="username"]', username);
  await page.fill('input[autocomplete="email"]', email);
  await page.fill('input[autocomplete="new-password"]', password);
  await page.click('button[type="submit"]');
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('pageerror', (err) => consoleErrors.push(err.message));

  try {
    // --- Scenario 1: standard signup - confirm redirect to LOGIN, not dashboard ---
    const acct1 = { username: 'ScenarA', email: `scenario1_${rand}@example.com`, password: 'Test1234!' };
    await doSignup(page, acct1);
    await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
    const onLoginNotDashboard = page.url() === `${BASE}/login`;
    const successMsgVisible = await page.waitForSelector('text=Account created', { timeout: 5000 }).then(() => true).catch(() => false);
    log('Item 2 / Scenario 1: signup redirects to /login (not dashboard) with success message', onLoginNotDashboard && successMsgVisible, `url=${page.url()}`);

    // Confirm this account can actually log in (proves it was really created, not auto-logged-in)
    await page.fill('input[autocomplete="email"]', acct1.email);
    await page.fill('input[autocomplete="current-password"]', acct1.password);
    await page.click('button[type="submit"]');
    await page.waitForURL(BASE + '/', { timeout: 10000 });
    log('Scenario 1: newly-signed-up account can log in and reach Dashboard', page.url() === BASE + '/');
    await page.click('text=Log out');
    await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });

    // --- Scenario 2: minimum-boundary valid inputs (3-char username, 8-char password) ---
    const acct2 = { username: 'Sc2', email: `scenario2_${rand}@example.com`, password: 'Ab1!cdEf' };
    await doSignup(page, acct2);
    const scen2Ok = await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 }).then(() => true).catch(() => false);
    log('Scenario 2: min-boundary username(3)/password(8) signup succeeds', scen2Ok, `url=${page.url()}`);

    // --- Scenario 3: maximum-boundary valid inputs (8-char username, 32-char password) ---
    const longPw = 'Ab1!' + 'x'.repeat(28); // 32 chars total
    const acct3 = { username: 'Scenar3x', email: `scenario3_${rand}@example.com`, password: longPw };
    await doSignup(page, acct3);
    const scen3Ok = await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 }).then(() => true).catch(() => false);
    log('Scenario 3: max-boundary username(8)/password(32) signup succeeds', scen3Ok, `pwLen=${longPw.length} url=${page.url()}`);

    // --- Scenario 4: duplicate email (reuse acct1's email) - clear generic error shown in UI, stays on signup page ---
    const acct4 = { username: 'ScenarD', email: acct1.email, password: 'Test5678!' };
    await doSignup(page, acct4);
    await page.waitForTimeout(1000);
    const stillOnSignup = page.url() === `${BASE}/signup`;
    const errorBannerVisible = await page.locator('text=Could not create your account').isVisible().catch(() => false);
    log('Scenario 4: duplicate-email signup shows generic error, stays on /signup', stillOnSignup && errorBannerVisible, `url=${page.url()} errorVisible=${errorBannerVisible}`);

    log('No console errors across all 4 signup scenarios', consoleErrors.length === 0, consoleErrors.join(' | '));

    await page.screenshot({ path: __dirname + '/shot_signup_dup_error.png', fullPage: true });
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
    await page.screenshot({ path: __dirname + '/shot_signup_error.png', fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
})();
