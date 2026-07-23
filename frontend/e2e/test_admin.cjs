const { chromium } = require('playwright');
const BASE = 'http://localhost:5175';

// Real admin credentials never belong in source - pull from env, same
// pattern as backend/app/scripts/seed_admin.py (ADMIN_1_EMAIL/ADMIN_1_PASSWORD).
// Run with: ADMIN_1_EMAIL=... ADMIN_1_PASSWORD=... node test_admin.cjs
const ADMIN_EMAIL = process.env.ADMIN_1_EMAIL;
const ADMIN_PASSWORD = process.env.ADMIN_1_PASSWORD;
if (!ADMIN_EMAIL || !ADMIN_PASSWORD) {
  console.error('Missing ADMIN_1_EMAIL / ADMIN_1_PASSWORD env vars - set them before running this script.');
  process.exit(1);
}

const results = [];
function log(step, ok, detail) {
  results.push({ step, ok, detail });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push('pageerror: ' + err.message));

  try {
    // Non-admin rejection test first (separate context/user)
    const nonAdminCreds = { email: 'accuracytest1@example.com', password: 'Test1234!' };
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
    await page.fill('input[autocomplete="email"]', nonAdminCreds.email);
    await page.fill('input[autocomplete="current-password"]', nonAdminCreds.password);
    await page.click('button[type="submit"]');
    const rejectedMsg = await page.waitForSelector('text=does not have admin access', { timeout: 8000 }).then(() => true).catch(() => false);
    log('Non-admin user is blocked from admin app with a clear message', rejectedMsg);
    log('Non-admin login does not redirect into the admin app', page.url().includes('/login'));

    // Admin login
    await page.fill('input[autocomplete="email"]', '');
    await page.fill('input[autocomplete="email"]', ADMIN_EMAIL);
    await page.fill('input[autocomplete="current-password"]', '');
    await page.fill('input[autocomplete="current-password"]', ADMIN_PASSWORD);
    await page.click('button[type="submit"]');
    await page.waitForURL(BASE + '/', { timeout: 10000 });
    log('Admin login succeeds and lands on Dashboard', page.url() === BASE + '/');

    await page.waitForSelector('text=Total users', { timeout: 20000 }).catch(() => {});
    await page.waitForTimeout(500);
    const bodyText = await page.locator('body').innerText();
    const hasTotalUsers = /Total users/.test(bodyText);
    const hasNumbers = /\d+/.test(bodyText);
    log('Dashboard/Telemetry shows real stat data', hasTotalUsers && hasNumbers);
    await page.screenshot({ path: __dirname + '/shot_admin_dashboard.png', fullPage: true });

    // Charts rendered (Recharts renders SVG)
    const svgCount = await page.locator('svg.recharts-surface').count();
    log('Dashboard renders Recharts charts', svgCount >= 2, `svgCount=${svgCount}`);

    // Users page
    await page.click('a:has-text("Users")');
    await page.waitForURL(`${BASE}/users`, { timeout: 8000 });
    await page.waitForTimeout(1000);
    const userRows = await page.locator('tbody tr').count();
    log('Users page shows real data (rows)', userRows > 0, `rows=${userRows}`);
    await page.screenshot({ path: __dirname + '/shot_admin_users.png', fullPage: true });

    // Click into a user detail page
    if (userRows > 0) {
      await page.locator('tbody tr').first().locator('a').first().click();
      await page.waitForURL(/\/users\/[a-f0-9]{24}$/, { timeout: 8000 });
      await page.waitForTimeout(1000);
      const detailText = await page.locator('body').innerText();
      log('User detail (drill-down) page shows sections', /Documents/.test(detailText) && /Export Activity/.test(detailText) && /Activity Log/.test(detailText));
      await page.screenshot({ path: __dirname + '/shot_admin_user_detail.png', fullPage: true });
    }

    // Documents page
    await page.goto(`${BASE}/documents`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    const docRows = await page.locator('tbody tr').count();
    log('Documents page (cross-user) shows real data', docRows > 0, `rows=${docRows}`);
    await page.screenshot({ path: __dirname + '/shot_admin_documents.png', fullPage: true });

    // Workbooks page
    await page.goto(`${BASE}/workbooks`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    const wbText = await page.locator('body').innerText();
    log('Workbooks page loads without error', !/Could not load/.test(wbText));
    await page.screenshot({ path: __dirname + '/shot_admin_workbooks.png', fullPage: true });

    // Logs page
    await page.goto(`${BASE}/logs`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    const logRows = await page.locator('tbody tr').count();
    log('Logs page shows real data', logRows > 0, `rows=${logRows}`);
    await page.screenshot({ path: __dirname + '/shot_admin_logs.png', fullPage: true });

    // Edit a user (round trip)
    await page.goto(`${BASE}/users`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(800);
    const editButtons = page.locator('button:has-text("Edit")');
    if (await editButtons.count() > 0) {
      await editButtons.first().click();
      const modalVisible = await page.locator('text=Edit user').isVisible().catch(() => false);
      log('Edit user modal opens', modalVisible);
      if (modalVisible) {
        await page.click('button:has-text("Cancel")');
      }
    }

    log('No console errors across admin app pages', consoleErrors.length === 0, consoleErrors.slice(0, 8).join(' | '));
  } catch (err) {
    log('UNCAUGHT ERROR', false, err.message);
    await page.screenshot({ path: __dirname + '/shot_admin_error.png', fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  console.log('\n=== SUMMARY ===');
  results.forEach((r) => console.log(`${r.ok ? 'PASS' : 'FAIL'}: ${r.step}`));
})();
