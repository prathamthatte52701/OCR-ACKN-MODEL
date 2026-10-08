// UI + API end-to-end check of the admin-approval / privacy / security features,
// one feature at a time (T1..T16 in the hardening list). Same shape as the other
// raw-Playwright scripts here: no runner, a `results` array, a SUMMARY at the end.
//
// Needs: backend running against a *_test database, `npm run dev` for frontend
// (5174) and admin (5175), and a seed file written by the seed helper with an
// admin plus users A and B (ids, emails, passwords):
//   E2E_SEED_FILE=path/to/seed.json SHOT_DIR=path/to/screenshots node test_approval_features.cjs
const { chromium } = require('playwright')
const fs = require('fs')

const FRONT = 'http://localhost:5174'
const ADMIN = 'http://localhost:5175'
const API = 'http://127.0.0.1:8000/api'
const seed = JSON.parse(fs.readFileSync(process.env.E2E_SEED_FILE, 'utf8'))
const SHOTS = process.env.SHOT_DIR || '.'
const PW = seed.A.password
const results = []

function log(feature, step, ok, detail) {
  results.push({ feature, step, ok, detail })
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${feature} | ${step}${detail ? ' - ' + detail : ''}`)
}

async function setVal(page, selector, value, nth = 0) {
  await page.locator(selector).nth(nth).fill(value)
}

async function adminLogin(page) {
  await page.goto(`${ADMIN}/login`)
  await setVal(page, 'input[type=email]', seed.admin.email)
  await setVal(page, 'input[type=password]', seed.admin.password)
  await page.click('button[type=submit]')
  await page.waitForTimeout(2000)
}

async function userLogin(page, email, password) {
  // start from a clean browser session so a previous user's token cannot leak into this login
  await page.goto(`${FRONT}/login`)
  await page.evaluate(() => localStorage.clear())
  await page.goto(`${FRONT}/login`)
  await page.waitForSelector('input[type=email]')
  await setVal(page, 'input[type=email]', email)
  await setVal(page, 'input[type=password]', password)
  await page.click('button[type=submit]')
  await page.waitForTimeout(2500)
}

;(async () => {
  const browser = await chromium.launch({ headless: true })
  const mk = async () => (await browser.newContext({ viewport: { width: 1360, height: 820 } })).newPage()
  const shot = (page, name) => page.screenshot({ path: `${SHOTS}/${name}.png` })
  const user = await mk()
  const admin = await mk()

  try {
    // ---------------- T1 + T4: signup -> pending; login messages (user UI)
    await user.goto(`${FRONT}/signup`)
    await setVal(user, 'input:not([type=email]):not([type=password])', 'carol')
    await setVal(user, 'input[type=email]', 'carol@looptest.local')
    await setVal(user, 'input[type=password]', PW)
    await user.click('button[type=submit]')
    await user.waitForTimeout(2000)
    const afterSignup = await user.locator('body').innerText()
    log('T1/T4 signup', 'signup lands on login with "Waiting for admin approval."', user.url().includes('/login') && afterSignup.includes('Waiting for admin approval'), user.url())
    await shot(user, 'T4_after_signup')

    await userLogin(user, 'carol@looptest.local', PW)
    const pendingText = await user.locator('body').innerText()
    const tokenAfterPending = await user.evaluate(() => JSON.stringify(localStorage))
    log('T1/T4 login', 'pending user sees "Waiting for admin approval." and stays on login', pendingText.includes('Waiting for admin approval.') && user.url().includes('/login'))
    log('T1 login', 'no token stored for pending user', !/token/i.test(tokenAfterPending) || !/eyJ/.test(tokenAfterPending), tokenAfterPending.slice(0, 60))
    await shot(user, 'T4_pending_login')

    await userLogin(user, 'carol@looptest.local', 'Wr0ng!pass9')
    log('T2 login', 'wrong password shows generic error', (await user.locator('body').innerText()).includes('Invalid email or password.'))

    // ---------------- T11 + T12 (signup UI): weak-format password, length attrs
    await user.goto(`${FRONT}/signup`)
    await setVal(user, 'input:not([type=email]):not([type=password])', 'dave')
    await setVal(user, 'input[type=email]', 'dave@looptest.local')
    await setVal(user, 'input[type=password]', 'password1')
    await user.click('button[type=submit]')
    await user.waitForTimeout(1800)
    log('T11 passwords', 'password without capital/special character is rejected with the rule text', (await user.locator('body').innerText()).includes('special character'))
    await shot(user, 'T11_weak_format_password')
    const maxLen = await user.locator('input[type=password]').first().getAttribute('maxlength')
    log('T12/T11 limits', 'password input maxlength is 64', maxLen === '64', `maxlength=${maxLen}`)

    // ---------------- T5 + T3: admin panel
    await adminLogin(admin)
    // the badge comes from a request the layout fires after login - give it a moment
    await admin.waitForFunction(() => /Users\s*\d/.test(document.querySelector('nav')?.innerText || ''), null, { timeout: 8000 }).catch(() => {})
    const navText = await admin.locator('nav').first().innerText()
    log('T5 admin nav', 'Users nav shows a pending badge', /Users\s*1/.test(navText.replace(/\n/g, ' ')), navText.replace(/\n/g, ' '))
    await shot(admin, 'T5_dashboard_badge')
    await admin.goto(`${ADMIN}/users`)
    await admin.waitForTimeout(2500)
    const tabs = await admin.$$eval('[role=tab]', (e) => e.map((x) => x.innerText.replace(/\s+/g, ' ')))
    log('T5 admin tabs', 'Approved / Pending (badge) / Rejected tabs exist', tabs.length === 3 && tabs[1].includes('1'), JSON.stringify(tabs))
    const selected = await admin.$$eval('[role=tab][aria-selected=true]', (e) => e.map((x) => x.innerText))
    log('T5 admin tabs', 'page opens on the Pending tab when requests are waiting', selected[0]?.startsWith('Pending'), JSON.stringify(selected))
    const row = admin.locator('tbody tr', { hasText: 'carol@looptest.local' })
    await admin.waitForSelector('[role=tab][aria-selected=true]:has-text("Pending")', { timeout: 8000 }).catch(() => {})
    await row.first().waitFor({ timeout: 8000 }).catch(() => {})
    log('T5 admin pending', 'carol is listed with Approve and Reject buttons', (await row.count()) === 1 && (await row.locator('button:has-text("Approve")').count()) === 1 && (await row.locator('button:has-text("Reject")').count()) === 1)
    await shot(admin, 'T5_pending_tab')

    await row.locator('button:has-text("Approve")').click()
    await admin.waitForTimeout(1800)
    log('T3 approve', 'carol leaves the Pending list after Approve', (await admin.locator('tbody tr', { hasText: 'carol@looptest.local' }).count()) === 0)
    await userLogin(user, 'carol@looptest.local', PW)
    log('T3 approve', 'carol can now log in (lands on the app)', !user.url().includes('/login'), user.url())
    await shot(user, 'T3_after_approval_login')

    await admin.click('[role=tab]:has-text("Approved")')
    await admin.waitForTimeout(1500)
    const aRow = admin.locator('tbody tr', { hasText: 'carol@looptest.local' })
    log('T5 revoke', 'approved user shows a Revoke button; admin rows do not', (await aRow.locator('button:has-text("Revoke")').count()) === 1 && (await admin.locator('tbody tr', { hasText: 'uiadmin@looptest.local' }).locator('button:has-text("Revoke")').count()) === 0)
    await aRow.locator('button:has-text("Revoke")').click()
    await admin.waitForTimeout(1800)
    await admin.click('[role=tab]:has-text("Rejected")')
    await admin.waitForTimeout(1500)
    const rRow = admin.locator('tbody tr', { hasText: 'carol@looptest.local' })
    log('T3 reject', 'revoked user appears under Rejected with Re-approve', (await rRow.count()) === 1 && (await rRow.locator('button:has-text("Re-approve")').count()) === 1)
    await shot(admin, 'T5_rejected_tab')
    // old session is dead; fresh login shows the rejected message
    await user.reload()
    await user.waitForTimeout(2500)
    log('T3 reject', 'revoked user open session is sent back to login after reload', user.url().includes('/login'), user.url())
    await userLogin(user, 'carol@looptest.local', PW)
    log('T4 login', 'rejected user sees "Your request was not approved. Contact the admin."', (await user.locator('body').innerText()).includes('Your request was not approved. Contact the admin.'))
    await shot(user, 'T4_rejected_login')

    await rRow.locator('button:has-text("Re-approve")').click()
    await admin.waitForTimeout(1800)
    log('T3 re-approve', 'Re-approve removes carol from Rejected', (await admin.locator('tbody tr', { hasText: 'carol@looptest.local' }).count()) === 0)

    // ---------------- T9: email admin-only
    await userLogin(user, 'carol@looptest.local', PW)
    await user.goto(`${FRONT}/profile`)
    await user.waitForTimeout(1500)
    await user.click('button:has-text("Edit")')
    await user.waitForTimeout(500)
    const emailInput = user.locator('input[type=email]')
    log('T9 email', 'profile edit shows the email read-only (disabled)', (await emailInput.count()) === 1 && (await emailInput.first().isDisabled()))
    await shot(user, 'T9_profile_email_readonly')
    await admin.click('[role=tab]:has-text("Approved")')
    await admin.waitForTimeout(1500)
    const cRow = admin.locator('tbody tr', { hasText: 'carol@looptest.local' })
    await cRow.locator('button:has-text("Edit")').click()
    await admin.waitForTimeout(600)
    await admin.locator('input[type=email]').fill('carol2@looptest.local')
    await admin.click('button:has-text("Save")')
    await admin.waitForTimeout(1800)
    log('T9 email', 'admin changes carol\'s email in the Edit dialog', (await admin.locator('tbody tr', { hasText: 'carol2@looptest.local' }).count()) === 1)
    const stillIn = await user.evaluate(async () => {
      const t = JSON.parse(localStorage.getItem('auth-storage') || '{}')
      return JSON.stringify(t).slice(0, 10)
    })
    const oldTokenStatus = await user.evaluate(async () => {
      const raw = Object.values(localStorage).join(' ')
      const m = raw.match(/eyJ[\w-]+\.[\w-]+\.[\w-]+/)
      if (!m) return 'no-token'
      const r = await fetch('/api/auth/me', { headers: { Authorization: 'Bearer ' + m[0] } })
      return r.status
    })
    log('T9 email', 'email change signs carol out (old token 401)', oldTokenStatus === 401 || oldTokenStatus === 'no-token', `${stillIn} ${oldTokenStatus}`)

    // ---------------- T6/T7/T10: export history privacy + isolation in the UI
    await userLogin(user, seed.A.email, PW)
    await user.goto(`${FRONT}/export-history`)
    await user.waitForTimeout(2200)
    const hist = await user.locator('body').innerText()
    log('T6 export history', 'user A sees own export row', hist.includes(seed.A.number))
    log('T6 export history', 'user A does NOT see user B\'s row or B\'s email', !hist.includes(seed.B.number) && !hist.includes(seed.B.email))
    await shot(user, 'T6_export_history_A')
    const dl = user.waitForEvent('download', { timeout: 8000 }).catch(() => null)
    await user.locator('button:has-text("Download")').first().click().catch(() => {})
    const download = await dl
    log('T7 workbook download', 'user A downloads own workbook from the page', !!download, download ? download.suggestedFilename() : 'no download')
    const tokA = await user.evaluate(() => (Object.values(localStorage).join(' ').match(/eyJ[\w-]+\.[\w-]+\.[\w-]+/) || [''])[0])
    const other = await user.evaluate(async ({ id, tok }) => {
      const r1 = await fetch(`/api/documents/export-history/workbook/${id}/download`, { headers: { Authorization: 'Bearer ' + tok } })
      const r2 = await fetch(`/api/documents/workbook/download?workbookId=${id}`, { headers: { Authorization: 'Bearer ' + tok } })
      return [r1.status, r2.status]
    }, { id: seed.B.workbook, tok: tokA })
    log('T7/T10 isolation', 'A cannot download B\'s workbook by id (404, 404)', other[0] === 404 && other[1] === 404, JSON.stringify(other))
    await user.goto(`${FRONT}/documents/${seed.B.doc}`)
    await user.waitForTimeout(2000)
    const bDocPage = await user.locator('body').innerText()
    log('T10 isolation', 'A opening B\'s document page shows not-found, no B data', !bDocPage.includes(seed.B.number), bDocPage.replace(/\s+/g, ' ').slice(0, 80))
    await shot(user, 'T10_other_users_doc')

    // ---------------- T8: admin access audit visible in the admin Logs page
    await admin.goto(`${ADMIN}/documents`)
    await admin.waitForTimeout(2000)
    await admin.goto(`${ADMIN}/workbooks`)
    await admin.waitForTimeout(2000)
    await admin.goto(`${ADMIN}/logs`)
    await admin.waitForTimeout(2000)
    const options = await admin.$$eval('select option', (o) => o.map((x) => x.value))
    for (const a of ['admin_access', 'user_approved', 'user_rejected', 'user_email_changed']) {
      log('T8 admin logs', `Logs filter lists "${a}"`, options.includes(a))
    }
    if (options.includes('admin_access')) {
      await admin.selectOption('select', 'admin_access')
      await admin.waitForTimeout(1800)
      const logsText = await admin.locator('body').innerText()
      log('T8 admin logs', 'admin_access entries are shown (documents/workbooks list)', logsText.includes('admin_access') && /documents|workbooks/.test(logsText))
      await shot(admin, 'T8_admin_logs')
    }

    // ---------------- T13: upload size (UI) + server ceiling
    await userLogin(user, seed.A.email, PW)
    await user.goto(`${FRONT}/upload`)
    await user.waitForTimeout(1500)
    await user.setInputFiles('input[type=file]', { name: 'big.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(5.5 * 1024 * 1024, 37) })
    await user.waitForTimeout(1000)
    log('T13 upload', 'UI rejects a 5.5 MB file with the size message', (await user.locator('body').innerText()).includes('5 MB'))
    await shot(user, 'T13_upload_too_big')
    // sent from Node (not the browser): the server answers 413 and drops the connection
    // before the body is read, which a browser fetch reports as a network error
    const res = await user.request.post(`${API}/documents/upload`, {
      headers: { Authorization: 'Bearer ' + tokA },
      multipart: { documentType: 'Tax Invoice', document: { name: 'huge.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(7 * 1024 * 1024, 37) } },
    }).catch((e) => ({ status: () => 'net-err: ' + e.message.slice(0, 40) }))
    const code = res.status()
    log('T13 upload', 'server answers 413 to a 7 MB request', code === 413, String(code))

    // ---------------- T14/T15/T16 + T12 via the API
    // against the backend itself: the Vite dev server answers /docs with the SPA page
    const docs = (await user.request.get('http://127.0.0.1:8000/docs')).status()
    log('T14 safe defaults', '/docs is hidden (404)', docs === 404, String(docs))
    const oapi = (await user.request.get('http://127.0.0.1:8000/openapi.json')).status()
    log('T14 safe defaults', '/openapi.json is hidden (404)', oapi === 404, String(oapi))
    const big = await user.evaluate(async (e) => {
      const r = await fetch('/api/auth/login', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ email: e, password: 'x'.repeat(5000) }) })
      return r.status
    }, seed.A.email)
    log('T12 field limits', '5000-char password rejected with 422 (not 500)', big === 422, String(big))

    // ---------------- T3: admin delete flow + approval of a second signup via UI
    await admin.goto(`${ADMIN}/users`)
    await admin.waitForTimeout(2000)
    await admin.click('[role=tab]:has-text("Approved")')
    await admin.waitForTimeout(1200)
    await admin.locator('tbody tr', { hasText: 'carol2@looptest.local' }).locator('button:has-text("Delete")').click()
    await admin.waitForTimeout(500)
    await admin.click('button:has-text("Yes, Delete")')
    await admin.waitForTimeout(1800)
    log('T3 delete', 'admin deletes a user from the Approved tab', (await admin.locator('tbody tr', { hasText: 'carol2@looptest.local' }).count()) === 0)
  } catch (err) {
    log('RUNNER', 'unexpected error', false, err.message.split('\n')[0])
    await shot(user, 'ERROR_user').catch(() => {})
    await shot(admin, 'ERROR_admin').catch(() => {})
  } finally {
    await browser.close()
  }

  const failed = results.filter((r) => !r.ok)
  console.log('\n=== SUMMARY ===')
  console.log(`${results.length - failed.length}/${results.length} passed`)
  failed.forEach((f) => console.log(`FAILED: ${f.feature} | ${f.step} - ${f.detail || ''}`))
  fs.writeFileSync(`${SHOTS}/e2e_results.json`, JSON.stringify(results, null, 1))
  process.exit(failed.length ? 1 : 0)
})()
