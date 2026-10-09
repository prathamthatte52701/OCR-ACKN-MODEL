// AI "confidence" is gone from the UI: My Documents cards, Document Detail (also reached by a
// single upload) and the bulk review show no badge / colored border, and the same values.
// The mocked API deliberately still sends LEGACY *Confidence keys (low ones) to prove the UI
// ignores them. Needs only `npm run dev` in frontend (5174); API mocked with page.route.
//
//   node test_no_confidence_ui.cjs
const { chromium } = require('playwright')
const fs = require('fs')
const os = require('os')
const path = require('path')

const BASE = 'http://localhost:5174'
const SHOTS = process.env.SHOT_DIR || ''
const results = []
const consoleErrors = []
function log(step, ok, detail) {
  results.push({ step, ok, detail })
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`)
}

const LEGACY = { taxInvoiceNoConfidence: 5, referenceNoConfidence: 5, numberConfidence: 5, dateConfidence: 5 }
const tax = { _id: 'dt1', autoName: 'dt1', originalFilename: 'inv.pdf', documentType: 'Tax Invoice', uploadStatus: 'processed', taxInvoiceNo: 'G0027704827', referenceNo: '9800532362', date: '02/05/2026', exported: false, createdAt: '2026-05-02T10:00:00Z', ...LEGACY }
const dc = { _id: 'dd1', autoName: 'dd1', originalFilename: 'ch.pdf', documentType: 'Delivery Challan', uploadStatus: 'processed', number: '820260534', date: null, exported: false, createdAt: '2026-05-02T10:00:00Z', ...LEGACY }
const DOCS = { dt1: tax, dd1: dc }

;(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'noconf-'))
  const files = []
  for (let i = 0; i < 10; i++) { const p = path.join(dir, `fake${i}.pdf`); fs.writeFileSync(p, `%PDF-1.4 fake ${i}\n`); files.push(p) }
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  await context.addInitScript(() => localStorage.setItem('ackintel_token', 'mock.jwt.token'))
  const page = await context.newPage()
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 160)) })
  page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message.slice(0, 160)))
  const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  const bulkDoc = (k) => ({ _id: `bk-${k}`, uploadStatus: 'processed', taxInvoiceNo: `G00000000${k}`, referenceNo: `98000000${k}`, date: '01/01/2026', exported: false, ...LEGACY })
  await page.route((u) => new URL(u).pathname.startsWith('/api/'), async (route) => {
    const req = route.request(); const p = new URL(req.url()).pathname.replace(/^\/api/, ''); const m = req.method()
    if (p === '/health') return json(route, { status: 'ok' })
    if (p === '/auth/me') return json(route, { user: { id: 'u1', username: 'mockuser', email: 'mock@looptest.local', role: 'user' } })
    if (p === '/documents' && m === 'GET') return json(route, { documents: [tax, dc], totalDocuments: 2, totalPages: 1, currentPage: 1, byDocumentType: { 'Tax Invoice': 1, 'Delivery Challan': 1 } })
    if (p === '/documents/upload' && m === 'POST') return json(route, { document: { _id: 'dt1' } }, 201)
    if (p === '/documents/bulk-upload' && m === 'POST') return json(route, { results: files.map((_, k) => ({ document: { _id: `bk-${k}` } })) }, 201)
    let mt = p.match(/^\/documents\/bk-(\d+)$/); if (mt && m === 'GET') return json(route, { document: bulkDoc(Number(mt[1])) })
    mt = p.match(/^\/documents\/(dt1|dd1)$/); if (mt && m === 'GET') return json(route, { document: DOCS[mt[1]] })
    return json(route, {})
  })

  const noBadge = () => page.locator('[aria-label*="onfidence"], [title*="onfidence"]').count()
  // field rows = the card around each "Edit" button; none may carry a status-colored border
  const noColoredBorder = () => page.evaluate(() => [...document.querySelectorAll('button')].filter((b) => b.textContent.trim() === 'Edit').every((b) => !/border-(red|rose|emerald|amber|green)-/.test(b.closest('div.rounded-xl')?.className || '')))
  const noHScroll = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)

  try {
    for (const [w, h] of [[1280, 900], [390, 800]]) {
      await page.setViewportSize({ width: w, height: h })
      const tag = `${w}px`
      await page.goto(`${BASE}/documents`); await page.waitForSelector('article', { timeout: 10000 })
      log(`${tag} My Documents: no badge, no colored border`, (await noBadge()) === 0 && (await noColoredBorder()))
      const cls = await page.locator('article').first().getAttribute('class')
      log(`${tag} My Documents: card uses the neutral border`, cls.includes('border-white/12') && cls.includes('hover:border-blue-300/40'))
      const t = (await page.locator('article').allInnerTexts()).join(' ')
      log(`${tag} My Documents: values still shown`, t.includes('G0027704827') && t.includes('820260534'))
      log(`${tag} My Documents: no horizontal scroll`, await noHScroll())
      if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `noconf_list_${w}.png`) })

      for (const id of ['dt1', 'dd1']) {
        await page.goto(`${BASE}/documents/${id}`); await page.waitForSelector('text=Extracted Fields', { timeout: 10000 })
        const body = await page.locator('body').innerText()
        const want = id === 'dt1' ? ['TAX INVOICE No.', 'G0027704827', 'Reference No.', '9800532362', '02/05/2026'] : ['Delivery Challan No.', '820260534', 'Not available']
        log(`${tag} Detail ${id}: values/labels intact`, want.every((x) => body.includes(x)), want.filter((x) => !body.includes(x)).join(','))
        log(`${tag} Detail ${id}: no badge, no colored border`, (await noBadge()) === 0 && (await noColoredBorder()))
        const edits = await page.locator('button:has-text("Edit")').count()
        log(`${tag} Detail ${id}: one Edit button per field`, edits === (id === 'dt1' ? 3 : 2), `edits=${edits}`)
        log(`${tag} Detail ${id}: no horizontal scroll`, await noHScroll())
        if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `noconf_detail_${id}_${w}.png`) })
      }

      // single upload -> lands on the detail page
      await page.goto(`${BASE}/upload`); await page.waitForTimeout(800)
      await page.setInputFiles('input[type=file]', files[0])
      await page.locator('button:has-text("Upload")').last().click().catch(() => {})
      await page.waitForURL('**/documents/dt1', { timeout: 15000 }).catch(() => {})
      await page.waitForSelector('text=Extracted Fields', { timeout: 10000 }).catch(() => {})
      log(`${tag} single upload result: reached detail, no badge/border`, page.url().endsWith('/documents/dt1') && (await noBadge()) === 0 && (await noColoredBorder()), page.url())

      // bulk review
      await page.goto(`${BASE}/upload`); await page.waitForTimeout(800)
      await page.click('button:has-text("Bulk Upload")')
      await page.setInputFiles('input[type=file]', files)
      await page.waitForTimeout(500)
      await page.locator('button:has-text("Upload All")').click()
      await page.waitForSelector('text=Review Results', { timeout: 60000 }).catch(() => {})
      const bb = await page.locator('body').innerText()
      log(`${tag} bulk review: values shown`, bb.includes('G000000000') && bb.includes('980000000'))
      log(`${tag} bulk review: no badge, no colored border`, (await noBadge()) === 0 && (await noColoredBorder()))
      log(`${tag} bulk review: Edit buttons present`, (await page.locator('button:has-text("Edit")').count()) >= 3)
      log(`${tag} bulk review: no horizontal scroll`, await noHScroll())
      if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `noconf_bulk_${w}.png`) })
    }
  } catch (err) {
    log('RUNNER', false, err.message.split('\n')[0])
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'noconf_ERROR.png') }).catch(() => {})
  } finally {
    log('console: zero errors during the whole run', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '))
    await browser.close()
    fs.rmSync(dir, { recursive: true, force: true })
  }
  const failed = results.filter((r) => !r.ok)
  console.log('\n=== SUMMARY ===')
  console.log(`${results.length - failed.length}/${results.length} passed`)
  failed.forEach((f) => console.log(`FAILED: ${f.step} - ${f.detail || ''}`))
  process.exit(failed.length ? 1 : 0)
})()
