// My Documents "Save All": only processed documents are sent, blocked-by-workbook flow, grouped
// result toasts, timeout handling, double-click guard. Same shape as the other raw-Playwright
// scripts here (results[] of {step, ok, detail}, a SUMMARY). Needs only `npm run dev` in frontend
// (5174): the API is mocked with page.route, so no backend / OCR / DB.
//
//   node test_save_all.cjs
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

const mkDoc = (id, status, extra = {}) => ({
  _id: id, autoName: id, originalFilename: `${id}.pdf`, documentType: 'Delivery Challan', uploadStatus: status,
  number: `82000${id.replace(/\D/g, '').padStart(4, '0')}`, date: '05/10/2026',
  edited: false, exported: false, createdAt: '2026-10-05T10:00:00Z', ...extra,
})

;(async () => {
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1360, height: 1000 } })
  await context.addInitScript(() => localStorage.setItem('ackintel_token', 'mock.jwt.token'))
  const page = await context.newPage()
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 160)) })
  page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message.slice(0, 160)))

  // ---- scripted mock server -------------------------------------------------------------
  const state = { docs: [], bulkRequests: [], newFileRequests: [], listRequests: 0, bulkHandler: null }
  const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  await page.route((u) => new URL(u).pathname.startsWith('/api/'), async (route) => {
    const req = route.request()
    const p = new URL(req.url()).pathname.replace(/^\/api/, '')
    const m = req.method()
    if (p === '/health') return json(route, { status: 'ok' })
    if (p === '/auth/me') return json(route, { user: { id: 'u1', username: 'mockuser', email: 'mock@looptest.local', role: 'user' } })
    if (p === '/documents' && m === 'GET') {
      state.listRequests++
      return json(route, { documents: state.docs, totalDocuments: state.docs.length, totalPages: 1, currentPage: 1 })
    }
    if (p === '/documents/bulk-save' && m === 'POST') {
      const ids = JSON.parse(req.postData() || '{}').documentIds || []
      state.bulkRequests.push(ids)
      return state.bulkHandler(route, ids, state.bulkRequests.length)
    }
    if (p === '/documents/new-excel-file' && m === 'POST') {
      state.newFileRequests.push(JSON.parse(req.postData() || '{}').filename)
      return json(route, { message: 'New Excel workbook started.', filename: JSON.parse(req.postData() || '{}').filename, year: 2026 })
    }
    return json(route, {})
  })

  const ok = (ids, extra = {}) => ({ message: `${ids.length}/${ids.length} saved successfully.`, succeeded: ids, failed: [], blocked: null, notAttempted: [], dateFallback: [], ...extra })
  const saveAllBtn = () => page.locator('button:has-text("Save All")').first()
  const toastText = async () => {
    await page.waitForSelector('[data-sonner-toast]', { timeout: 6000 })
    return (await page.locator('[data-sonner-toast]').allInnerTexts()).join(' || ').replace(/\s+/g, ' ')
  }
  async function openPage(docs) {
    state.docs = docs
    state.bulkRequests = []
    state.newFileRequests = []
    await page.goto(`${BASE}/documents`)
    await page.waitForSelector('button:has-text("Save All")', { timeout: 10000 })
    await page.waitForTimeout(500)
  }
  const confirmDialog = () => page.locator('[role=dialog]:has-text("Save all documents on this page?")')
  const clearToasts = async () => { await page.evaluate(() => document.querySelectorAll('[data-sonner-toast]').forEach((t) => t.remove())); await page.waitForTimeout(150) }

  try {
    // 1. only processed ids are sent; dialog states the split
    state.bulkHandler = (route, ids) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ok(ids)) })
    await openPage([mkDoc('d1', 'processed'), mkDoc('d2', 'failed'), mkDoc('d3', 'processed'), mkDoc('d4', 'uploaded'), mkDoc('d5', 'processed'), mkDoc('d6', 'uploaded', { uploadStatus: 'processing' })])
    await saveAllBtn().click()
    await confirmDialog().waitFor({ timeout: 5000 })
    const dlg = (await confirmDialog().innerText()).replace(/\s+/g, ' ')
    log('confirm dialog says "3 will be saved, 3 skipped (not processed yet)"', dlg.includes('3 will be saved, 3 skipped (not processed yet)'), dlg.slice(0, 140))
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'saveall_1_confirm.png') })
    await page.locator('button:has-text("Yes, Save All")').click()
    await page.waitForTimeout(1200)
    log('only the 3 processed ids are sent (failed / uploaded / processing never are)', state.bulkRequests.length === 1 && JSON.stringify(state.bulkRequests[0]) === JSON.stringify(['d1', 'd3', 'd5']), JSON.stringify(state.bulkRequests))
    log('success toast "3 saved successfully."', (await toastText()).includes('3 saved successfully.'))

    // 2. nothing processed -> info toast, no dialog, no request
    await clearToasts()
    await openPage([mkDoc('f1', 'failed'), mkDoc('f2', 'uploaded')])
    await saveAllBtn().click()
    const t2 = await toastText()
    log('all-failed page: info toast, no dialog, no request', t2.includes('Nothing to save') && (await confirmDialog().count()) === 0 && state.bulkRequests.length === 0, t2.slice(0, 100))

    // 3. no skipped -> dialog has no "skipped" part
    await clearToasts()
    await openPage([mkDoc('g1', 'processed'), mkDoc('g2', 'processed')])
    await saveAllBtn().click()
    await confirmDialog().waitFor()
    const dlg3 = (await confirmDialog().innerText()).replace(/\s+/g, ' ')
    log('clean page: "2 will be saved." without a skipped part', dlg3.includes('2 will be saved.') && !dlg3.includes('skipped'), dlg3.slice(0, 120))
    await page.locator('button:has-text("Cancel")').click()
    await page.waitForTimeout(300)
    log('Cancel in the dialog sends nothing', state.bulkRequests.length === 0)

    // 4. blocked -> prompt -> new workbook -> ONE retry with only the unsaved ids
    await clearToasts()
    state.bulkHandler = (route, ids, n) => {
      const body = n === 1
        ? { message: '1/3 saved successfully.', succeeded: [ids[0]], failed: [], blocked: { error: 'NO_ACTIVE_WORKBOOK', year: 2026, message: 'No active Excel workbook yet. Name your first workbook to continue.' }, notAttempted: ids.slice(1), dateFallback: [] }
        : ok(ids)
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    }
    await openPage([mkDoc('b1', 'processed'), mkDoc('b2', 'processed'), mkDoc('b3', 'processed'), mkDoc('b4', 'failed')])
    await saveAllBtn().click()
    await page.locator('button:has-text("Yes, Save All")').click()
    await page.locator('[role=dialog] input').waitFor({ timeout: 6000 })
    const promptText = (await page.locator('[role=dialog]').innerText()).replace(/\s+/g, ' ')
    log('blocked: workbook-name prompt appears with the server message', promptText.includes('Name your first workbook for 2026') && promptText.includes('No active Excel workbook yet'), promptText.slice(0, 110))
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'saveall_2_prompt.png') })
    await page.locator('[role=dialog] input').fill('MyBook')
    await page.locator('[role=dialog] button:has-text("OK")').click()
    await page.waitForTimeout(1500)
    log('blocked: new-excel-file called once with the typed name', JSON.stringify(state.newFileRequests) === JSON.stringify(['MyBook']), JSON.stringify(state.newFileRequests))
    log('blocked: exactly 2 bulk-save requests; the retry holds ONLY the not-yet-saved ids (b1 never re-sent)', state.bulkRequests.length === 2 && JSON.stringify(state.bulkRequests[1]) === JSON.stringify(['b2', 'b3']) && !state.bulkRequests[1].includes('b1'), JSON.stringify(state.bulkRequests))
    log('blocked: final toast counts all 3 saved', (await toastText()).includes('3 saved successfully.'))

    // 5. blocked and the user cancels the prompt -> no workbook, no retry
    await clearToasts()
    state.bulkHandler = (route, ids) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ message: '0/2 saved successfully.', succeeded: [], failed: [], blocked: { error: 'NEED_NEW_WORKBOOK', year: 2026, message: 'The year changed to 2026. Create a new workbook for 2026 to continue.' }, notAttempted: ids, dateFallback: [] }) })
    await openPage([mkDoc('c1', 'processed'), mkDoc('c2', 'processed')])
    await saveAllBtn().click()
    await page.locator('button:has-text("Yes, Save All")').click()
    await page.locator('[role=dialog] input').waitFor({ timeout: 6000 })
    log('year rollover prompt title', (await page.locator('[role=dialog]').innerText()).includes('New workbook needed for 2026'))
    await page.keyboard.press('Escape')
    await page.waitForTimeout(1000)
    log('cancelled prompt: no workbook created and no retry', state.newFileRequests.length === 0 && state.bulkRequests.length === 1, `newFile=${state.newFileRequests.length} bulk=${state.bulkRequests.length}`)
    log('cancelled prompt: toast says nothing was saved', (await toastText()).includes('No workbook name given'))

    // 6. grouped failure reasons + date fallback in one toast
    await clearToasts()
    state.bulkHandler = (route, ids) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ok([ids[0], ids[1]], { failed: [{ documentId: ids[2], reason: 'The Excel file is busy or open. Close it in Excel and try again.' }, { documentId: ids[3], reason: 'The Excel file is busy or open. Close it in Excel and try again.' }, { documentId: ids[4], reason: 'Document not found.' }], dateFallback: [ids[1]] })) })
    await openPage(['e1', 'e2', 'e3', 'e4', 'e5'].map((id) => mkDoc(id, 'processed')))
    await saveAllBtn().click()
    await page.locator('button:has-text("Yes, Save All")').click()
    await page.waitForTimeout(1200)
    const t6 = await toastText()
    log('result toast: 2 saved, 3 failed with GROUPED reasons ("... (2)"), date-fallback count', t6.includes('2 saved') && t6.includes('3 failed') && t6.includes('Close it in Excel and try again. (2)') && t6.includes('Document not found. (1)') && t6.includes('1 had no readable date'), t6.slice(0, 260))
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'saveall_3_grouped_toast.png') })

    // 7. timeout / network drop -> warning toast, list refetched, NO auto-retry
    await clearToasts()
    state.bulkHandler = (route) => route.abort('failed')
    await openPage([mkDoc('t1', 'processed'), mkDoc('t2', 'processed')])
    const listBefore = state.listRequests
    await saveAllBtn().click()
    await page.locator('button:has-text("Yes, Save All")').click()
    await page.waitForTimeout(2500)
    const t7 = await toastText()
    log('network failure: warning toast "Save may have partly completed..."', t7.includes('Save may have partly completed. Check Export History before saving again.'), t7.slice(0, 120))
    log('network failure: the documents list is refetched', state.listRequests > listBefore, `list GETs ${listBefore} -> ${state.listRequests}`)
    await page.waitForTimeout(1500)
    log('network failure: no automatic retry (still exactly 1 bulk-save request)', state.bulkRequests.length === 1, `bulk requests=${state.bulkRequests.length}`)
    // the browser itself logs the aborted request as a console error - expected for this step only
    for (let i = consoleErrors.length - 1; i >= 0; i--) if (/ERR_FAILED|Failed to load resource/.test(consoleErrors[i]) || /Network Error/.test(consoleErrors[i])) consoleErrors.splice(i, 1)

    // 8. double click sends ONE request (dialog appears once, one confirm, one request)
    await clearToasts()
    state.bulkHandler = async (route, ids) => { await new Promise((r) => setTimeout(r, 600)); return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ok(ids)) }) }
    await openPage([mkDoc('x1', 'processed'), mkDoc('x2', 'processed')])
    await saveAllBtn().dblclick()
    await page.waitForTimeout(600)
    log('double click opens a single confirm dialog', (await confirmDialog().count()) === 1)
    await page.locator('button:has-text("Yes, Save All")').dblclick()
    await page.waitForTimeout(2000)
    log('double click on Save All + double click on confirm -> exactly 1 request', state.bulkRequests.length === 1, `requests=${state.bulkRequests.length}`)

    // 9. mobile viewport
    await page.setViewportSize({ width: 390, height: 800 })
    await page.waitForTimeout(400)
    log('390x800: no horizontal scroll on My Documents', await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
  } catch (err) {
    log('RUNNER', false, err.message.split('\n')[0])
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'saveall_ERROR.png') }).catch(() => {})
  } finally {
    log('console: zero errors during the whole run', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '))
    await browser.close()
  }

  const failed = results.filter((r) => !r.ok)
  console.log('\n=== SUMMARY ===')
  console.log(`${results.length - failed.length}/${results.length} passed`)
  failed.forEach((f) => console.log(`FAILED: ${f.step} - ${f.detail || ''}`))
  if (SHOTS) fs.writeFileSync(path.join(SHOTS, 'saveall_results.json'), JSON.stringify(results, null, 1))
  process.exit(failed.length ? 1 : 0)
})()
