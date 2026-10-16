// Real browser check of the AI failure messages. Needs: backend on :8000 started on a *_test DB with
// GROQ_BASE_URL pointing at the local stub (groq_stub.py on :9099) and fake keys, the user app on :5174,
// and a seeded approved user t@looptest.local / Xq7!mZv#4Lp2. Never calls the real Groq API.
//   NODE_PATH=<node_modules with playwright> node test_ai_failure_ui.cjs
const { chromium } = require('playwright')
const fs = require('fs')
const BASE = 'http://localhost:5174'
const STUB = 'http://127.0.0.1:9099'
const SHOTS = process.env.SHOTS || 'E:/ACKN OCR model/design-ref/shots'
const PNG = process.env.SAMPLE_PNG
const results = []
const rec = (s, ok, d = '') => { results.push(ok); console.log(ok ? 'PASS' : 'FAIL', s, d) }
const errs = []
const setMode = (m) => fetch(`${STUB}/__mode/${m}`, { method: 'POST' })
const OLD = /Groq API key/i
const NEW = /AI service is not set up correctly/i

;(async () => {
  fs.mkdirSync(SHOTS, { recursive: true })
  const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || undefined })
  const page = await (await browser.newContext({ viewport: { width: 1366, height: 900 } })).newPage()
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errs.push(m.text().slice(0, 160)) })
  page.on('pageerror', (e) => errs.push('PE ' + e.message.slice(0, 160)))
  await page.goto(BASE + '/login')
  await page.fill('input[type=email]', 't@looptest.local')
  await page.fill('input[type=password]', 'Xq7!mZv#4Lp2')
  await page.click('button[type=submit]')
  await page.waitForURL(BASE + '/')

  // ---- single upload with the model "gone"
  await setMode('model_not_found')
  await page.goto(BASE + '/upload')
  await page.locator('input[type=file]').first().setInputFiles(PNG)
  await page.getByRole('button', { name: /Upload & Process/ }).click()
  await page.waitForSelector('text=/AI service is not set up correctly|Groq API key/', { timeout: 120000 })
  const t = await page.locator('body').innerText()
  rec('single: new user message shown (AI service is not set up correctly)', NEW.test(t))
  rec('single: the old "check the Groq API key" text is gone', !OLD.test(t))
  await page.screenshot({ path: `${SHOTS}/ai_fail_single_1366.png`, fullPage: true })

  // ---- find the failed document, open it, fix the "config" (stub -> ok), reprocess
  await setMode('ok')
  await page.goto(BASE + '/documents')
  await page.waitForSelector('article')
  await page.locator('article a:has-text("View")').first().click().catch(async () => { await page.locator('article a').first().click() })
  await page.waitForURL(/\/documents\/[0-9a-f]{24}/)
  await page.waitForFunction(() => !/Loading\.\.\./.test(document.body.innerText), null, { timeout: 30000 })
  await page.getByRole('button', { name: 'Reprocess' }).waitFor()
  const detail = await page.locator('body').innerText()
  rec('detail page of the failed document shows the new message', NEW.test(detail) && !OLD.test(detail))
  await page.screenshot({ path: `${SHOTS}/ai_fail_detail_1366.png`, fullPage: true })
  await page.getByRole('button', { name: 'Reprocess' }).click()
  await page.getByRole('button', { name: /Yes, Reprocess/ }).click()
  await page.waitForFunction(() => /Extracted Fields|TAX INVOICE No\.|Delivery Challan No\./.test(document.body.innerText), null, { timeout: 120000 })
  await page.waitForFunction(() => !/AI service is not set up correctly/.test(document.body.innerText), null, { timeout: 120000 })
  const after = await page.locator('body').innerText()
  rec('reprocess after the fix: error message gone, extracted fields shown', !NEW.test(after) && /(TAX INVOICE|Delivery Challan) No\./.test(after) && /Processed/.test(after), after.replace(/\s+/g, ' ').slice(0, 120))
  await page.screenshot({ path: `${SHOTS}/ai_fail_reprocessed_1366.png`, fullPage: true })

  // ---- bulk upload while the stub says 404 for every third call
  await setMode('cycle404')
  await page.goto(BASE + '/upload')
  await page.getByRole('button', { name: /Bulk Upload/ }).click()
  await page.locator('input[type=file]').first().setInputFiles([PNG, PNG, PNG, PNG])
  await page.getByRole('button', { name: /Upload All/ }).click()
  await page.waitForSelector('text=Review Results', { timeout: 180000 })
  let sawNew = false
  let sawOld = false
  for (let i = 0; i < 6; i++) {
    const body = await page.locator('body').innerText()
    if (NEW.test(body)) sawNew = true
    if (OLD.test(body)) sawOld = true
    const next = page.getByRole('button', { name: 'Next' })
    if (!(await next.count()) || !(await next.isEnabled())) break
    await next.click()
    await page.waitForTimeout(150)
  }
  rec('bulk: a failed file shows the new message, none shows the old one', sawNew && !sawOld, `new=${sawNew} old=${sawOld}`)
  await page.screenshot({ path: `${SHOTS}/ai_fail_bulk_1366.png`, fullPage: true })

  rec('console/page errors from our code: none', errs.length === 0, errs.slice(0, 3).join(' | '))
  await browser.close()
  console.log(`${results.filter(Boolean).length}/${results.length} passed`)
  process.exit(results.every(Boolean) ? 0 : 1)
})()
