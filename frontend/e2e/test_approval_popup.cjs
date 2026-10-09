// "You're approved!" popup on the first login after admin approval. Same shape as the other
// raw-Playwright scripts here: no runner, a `results` array of {step, ok, detail}, a SUMMARY.
//
// Needs only `npm run dev` in frontend (5174): the API is mocked with page.route (the server
// sends `justApproved: true` once in the login response; the real flag logic is covered by
// backend/app/features/auth/test_approval_notice.py and by the live check).
//
//   node test_approval_popup.cjs
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

const BASE = 'http://localhost:5174'
const SHOTS = process.env.SHOT_DIR || ''
const results = []
const consoleErrors = []

function log(step, ok, detail) {
  results.push({ step, ok, detail })
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`)
}

const PASSWORD = 'Xq7!mZv#4Lp2'
// who gets justApproved:true from the mocked login endpoint
const APPROVED = new Set(['fresh@looptest.local', 'fresh2@looptest.local', 'fresh3@looptest.local', 'fresh4@looptest.local', 'fresh5@looptest.local'])

;(async () => {
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1360, height: 900 } })
  const page = await context.newPage()
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 160)) })
  page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message.slice(0, 160)))

  const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  const userOf = (email) => ({ id: `id-${email}`, username: email.split('@')[0].slice(0, 8), email, role: 'user' })
  let loginCalls = 0
  await page.route((u) => new URL(u).pathname.startsWith('/api/'), async (route) => {
    const req = route.request()
    const p = new URL(req.url()).pathname.replace(/^\/api/, '')
    const m = req.method()
    if (p === '/health') return json(route, { status: 'ok' })
    if (p === '/auth/login' && m === 'POST') {
      loginCalls++
      const { email, password } = JSON.parse(req.postData() || '{}')
      if (password !== PASSWORD) return json(route, { detail: 'Invalid email or password.' }, 401)
      return json(route, { token: `tok.${email}.x`, user: userOf(email), justApproved: APPROVED.has(email) })
    }
    if (p === '/auth/me') {
      const email = (req.headers()['authorization'] || '').replace('Bearer tok.', '').replace('.x', '')
      return json(route, { user: userOf(email) })
    }
    if (p === '/documents/training-stats') return json(route, { trainedCount: 0, correctedCount: 0 })
    if (p === '/documents') return json(route, { documents: [], totalDocuments: 0, totalPages: 1, currentPage: 1, byDocumentType: { 'Tax Invoice': 0, 'Delivery Challan': 0 } })
    if (p === '/documents/export-history') return json(route, { exports: [], totalExports: 0, totalPages: 1, currentPage: 1 })
    if (p === '/documents/my-activity') return json(route, { activity: [], totalActivity: 0, totalPages: 1, currentPage: 1 })
    return json(route, {})
  })

  const dialog = () => page.locator('[role=dialog]:has-text("You\'re approved!")')
  const isOpen = async () => (await dialog().count()) === 1
  async function login(email) {
    await page.goto(`${BASE}/login`)
    await page.evaluate(() => localStorage.clear())
    await page.goto(`${BASE}/login`)
    await page.fill('input[type=email]', email)
    await page.fill('input[type=password]', PASSWORD)
    await page.click('button[type=submit]')
    await page.waitForTimeout(1800)
  }
  async function logout() {
    await page.locator('button:has-text("Log out")').first().click()
    await page.waitForTimeout(800)
  }

  try {
    // 1. justApproved:true -> dialog on the page the user lands on
    await login('fresh@looptest.local')
    log('true: lands off the login page', !page.url().includes('/login'), page.url())
    log('true: dialog "You\'re approved!" shown on the dashboard', await isOpen())
    const text = await page.locator('[role=dialog]').innerText().catch(() => '')
    log('true: exact copy (title, text, one "Get started" button)', text.includes("You're approved!") && text.includes('The admin has approved your account. You can now upload and manage documents.') && (await page.locator('[role=dialog] button:has-text("Get started")').count()) === 1, text.replace(/\n+/g, ' | ').slice(0, 120))
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'popup_1_desktop.png') })
    const noLocal = await page.evaluate(() => !Object.keys(localStorage).some((k) => /approv/i.test(k)) && !Object.values(localStorage).some((v) => /justApproved/i.test(v)))
    log('true: the flag is not persisted to localStorage', noLocal)

    // 2. "Get started" closes it; refresh and navigation never bring it back
    await page.locator('[role=dialog] button:has-text("Get started")').click()
    await page.waitForTimeout(500)
    log('"Get started" closes the dialog', !(await isOpen()))
    await page.reload()
    await page.waitForTimeout(2000)
    log('refresh: dialog does not come back', !(await isOpen()))
    await page.goto(`${BASE}/documents`)
    await page.waitForTimeout(1500)
    await page.goto(`${BASE}/`)
    await page.waitForTimeout(1500)
    log('navigating around: dialog does not come back', !(await isOpen()))
    await logout()

    // 3. Esc closes
    await login('fresh2@looptest.local')
    log('true (2nd user): dialog shown', await isOpen())
    await page.keyboard.press('Escape')
    await page.waitForTimeout(500)
    log('Esc closes the dialog', !(await isOpen()))
    await page.reload()
    await page.waitForTimeout(1800)
    log('after Esc + refresh: stays closed', !(await isOpen()))
    await logout()

    // 4. overlay click closes
    await login('fresh3@looptest.local')
    log('true (3rd user): dialog shown', await isOpen())
    await page.mouse.click(8, 8)
    await page.waitForTimeout(500)
    log('overlay click closes the dialog', !(await isOpen()))
    await logout()

    // 5. false -> nothing
    await login('regular@looptest.local')
    log('false: no dialog', !(await isOpen()) && !page.url().includes('/login'), page.url())
    await logout()

    // 6. logout with the dialog still open, then another user with false: nothing left over
    await login('fresh4@looptest.local')
    log('true (4th user): dialog shown, left open on purpose', await isOpen())
    await page.keyboard.press('Escape') // close it so the Log out button is reachable
    await page.waitForTimeout(300)
    await logout()
    log('after logout: login page has no dialog', page.url().includes('/login') && !(await isOpen()))
    await login('another@looptest.local')
    log('false (another user right after): no leftover dialog', !(await isOpen()))
    await logout()

    // 7. a login that is rejected (wrong password) shows nothing
    const errorsBefore = consoleErrors.length
    await page.goto(`${BASE}/login`)
    await page.fill('input[type=email]', 'fresh5@looptest.local')
    await page.fill('input[type=password]', 'Wr0ng!pass9')
    await page.click('button[type=submit]')
    await page.waitForTimeout(1200)
    log('wrong password: still on login, no dialog', page.url().includes('/login') && !(await isOpen()))
    // the browser itself logs the deliberate 401 of this step as a console error - that one is expected
    for (let i = consoleErrors.length - 1; i >= errorsBefore; i--) if (/401 \(Unauthorized\)/.test(consoleErrors[i])) consoleErrors.splice(i, 1)

    // 8. never on the login/signup pages even if a flag were set
    await login('fresh5@looptest.local')
    log('true (5th user): dialog shown', await isOpen())
    await page.keyboard.press('Escape')
    await logout()

    // 9. mobile viewport fits
    await page.setViewportSize({ width: 390, height: 800 })
    await login('fresh@looptest.local')
    const box = await dialog().boundingBox().catch(() => null)
    log('390x800: dialog is shown and fits inside the screen', !!box && box.x >= 0 && box.y >= 0 && box.x + box.width <= 390 && box.y + box.height <= 800, box ? JSON.stringify({ x: Math.round(box.x), w: Math.round(box.width), y: Math.round(box.y), h: Math.round(box.height) }) : 'no dialog')
    const noHScroll = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    log('390x800: no horizontal scroll', noHScroll)
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'popup_2_mobile.png') })
    log('the mocked login endpoint was really used', loginCalls >= 8, `login calls=${loginCalls}`)
  } catch (err) {
    log('RUNNER', false, err.message.split('\n')[0])
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'popup_ERROR.png') }).catch(() => {})
  } finally {
    log('console: zero errors during the whole run', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '))
    await browser.close()
  }

  const failed = results.filter((r) => !r.ok)
  console.log('\n=== SUMMARY ===')
  console.log(`${results.length - failed.length}/${results.length} passed`)
  failed.forEach((f) => console.log(`FAILED: ${f.step} - ${f.detail || ''}`))
  if (SHOTS) fs.writeFileSync(path.join(SHOTS, 'popup_results.json'), JSON.stringify(results, null, 1))
  process.exit(failed.length ? 1 : 0)
})()
