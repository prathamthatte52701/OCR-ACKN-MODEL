// Viewer break cases. All /api/ mocked. Usage: BASE=http://localhost:5191 node tests/test_viewer_break.cjs
const { chromium } = require('playwright')
const BASE = process.env.BASE || 'http://localhost:5191'
const results = []
const USER = { id: 'u1', username: 'tester', email: 't@x.com', role: 'user' }
function makePdf(n) {
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>']
  const kids = []
  for (let i = 0; i < n; i++) kids.push(`${4 + i * 2} 0 R`)
  objs.push(`<< /Type /Pages /Kids [${kids.join(' ')}] /Count ${n} >>`)
  objs.push('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
  for (let i = 0; i < n; i++) {
    objs.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents ${5 + i * 2} 0 R /Resources << /Font << /F1 3 0 R >> >> >>`)
    const s = `BT /F1 24 Tf 72 700 Td (Page ${i + 1}) Tj ET`
    objs.push(`<< /Length ${s.length} >>\nstream\n${s}\nendstream`)
  }
  let out = '%PDF-1.4\n'; const off = []
  objs.forEach((o, i) => { off.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n` })
  const x = out.length
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + off.map((o) => String(o).padStart(10, '0') + ' 00000 n \n').join('')
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`
  return Buffer.from(out, 'latin1')
}
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64')
const good = makePdf(3)
const CASES = [
  { n: '1 corrupt %PDF- garbage', mime: 'application/pdf', name: 'a.pdf', dl: { body: Buffer.from('%PDF-1.4\n\x00\x01garbage garbage not a pdf at all\n'), ct: 'application/pdf' } },
  { n: '2 0-byte as pdf', mime: 'application/pdf', name: 'a.pdf', dl: { body: Buffer.alloc(0), ct: 'application/pdf' } },
  { n: '3 0-byte as png', mime: 'image/png', name: 'a.png', dl: { body: Buffer.alloc(0), ct: 'image/png' } },
  { n: '4 truncated real pdf', mime: 'application/pdf', name: 'a.pdf', dl: { body: good.subarray(0, Math.floor(good.length * 0.4)), ct: 'application/pdf' } },
  { n: '5 download 500', mime: 'application/pdf', name: 'a.pdf', dl: { status: 500, body: Buffer.from('{"detail":"boom"}'), ct: 'application/json' } },
  { n: '6 download HTML', mime: 'application/pdf', name: 'a.pdf', dl: { body: Buffer.from('<html><body>login page</body></html>'), ct: 'text/html' } },
  { n: '7a valid PDF, doc mime image/png', mime: 'image/png', name: 'a.png', dl: { body: good, ct: 'application/pdf' } },
  { n: '7b PNG, doc mime application/pdf', mime: 'application/pdf', name: 'a.pdf', dl: { body: PNG, ct: 'image/png' } },
  { n: '7c valid PDF baseline', mime: 'application/pdf', name: 'a.pdf', dl: { body: good, ct: 'application/pdf' } },
  { n: '8 Back while 100pg PDF loading', mime: 'application/pdf', name: 'a.pdf', dl: { body: makePdf(100), ct: 'application/pdf', delay: 3000 }, backEarly: true },
]
const DOC = (c) => ({ id: 'd1', autoName: 'TaxInvoice_X', originalFilename: c.name, mimeType: c.mime, size: 1234, uploadStatus: 'processed', documentType: 'Tax Invoice', taxInvoiceNo: 'INV-1', referenceNo: 'R-1', date: '01/01/2025', createdAt: new Date().toISOString(), processedAt: new Date().toISOString(), filePurged: false, exported: false })

async function run(browser, c) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  await ctx.addInitScript(() => localStorage.setItem('ackintel_token', 'tok'))
  const pageErrors = [], consoleErrs = []
  await ctx.route((u) => new URL(u).pathname.startsWith('/api/'), async (route) => {
    const p = new URL(route.request().url()).pathname
    const json = (b) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(b) })
    if (p.endsWith('/auth/me')) return json({ user: USER })
    if (p.endsWith('/documents/d1/download')) {
      if (c.dl.delay) await new Promise((r) => setTimeout(r, c.dl.delay))
      return route.fulfill({ status: c.dl.status || 200, contentType: c.dl.ct, body: c.dl.body }).catch(() => {})
    }
    if (p.endsWith('/documents/d1')) return json({ document: DOC(c) })
    return json({ documents: [], total: 0, entries: [], rows: [], exports: [], workbooks: [], stats: {}, items: [] })
  })
  const page = await ctx.newPage()
  page.on('pageerror', (e) => pageErrors.push(e.message))
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') consoleErrs.push(`[${m.type()}] ${m.text()}`) })
  await page.goto(BASE + '/documents')
  await page.waitForTimeout(800)
  await page.evaluate(() => { history.pushState({}, '', '/documents/d1'); dispatchEvent(new PopStateEvent('popstate')) })
  const r = { case: c.n }
  const back = page.locator('button[aria-label="Go back"]')
  await page.getByRole('heading', { name: 'TaxInvoice_X' }).waitFor({ timeout: 8000 }).catch(() => {})
  if (c.backEarly) {
    await page.waitForTimeout(800)
    await back.first().click()
    await page.waitForTimeout(4500)
    r.path = new URL(page.url()).pathname
    r.fullCrash = await page.getByText('Something went wrong', { exact: true }).count()
    r.pageErrors = pageErrors; r.console = consoleErrs
    await ctx.close(); return r
  }
  await page.waitForTimeout(3000)
  const viewer = page.locator('[data-testid=document-viewer]')
  r.fullCrash = await page.getByText('Something went wrong', { exact: true }).count()
  r.title = await page.getByRole('heading', { name: 'TaxInvoice_X' }).count()
  r.viewerText = (await viewer.count()) ? (await viewer.innerText()).replace(/\s+/g, ' ') : null
  r.preview = await page.getByText('Preview unavailable').count()
  r.fileErr = await page.getByText('Could not load the original file.').count()
  r.boundary = await page.getByText('Could not load the viewer.').count()
  r.canvasPx = await page.evaluate(() => { const c = document.querySelector('canvas'); return c ? `${c.width}x${c.height}` : null })
  r.imgOk = await page.evaluate(() => { const i = document.querySelector('[data-testid=document-viewer] img'); return i ? i.naturalWidth : null })
  r.backEnabled = await back.first().isEnabled()
  // other buttons alive
  r.bodyButtons = await page.locator('button:visible').allInnerTexts()
  await back.first().click()
  await page.waitForTimeout(1200)
  r.pathAfterBack = new URL(page.url()).pathname
  r.crashAfterBack = await page.getByText('Something went wrong', { exact: true }).count()
  r.pageErrors = pageErrors; r.console = consoleErrs
  await page.screenshot({ path: `${process.env.SHOTS_DIR || require('os').tmpdir()}/viewer_${c.n.split(' ')[0]}.png` }).catch(() => {})
  await ctx.close()
  return r
}
;(async () => {
  const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || undefined })
  for (const c of CASES) { try { console.log(JSON.stringify(await run(browser, c))) } catch (e) { console.log(c.n, 'SCRIPT ERR', e.message) } }
  await browser.close()
})()
