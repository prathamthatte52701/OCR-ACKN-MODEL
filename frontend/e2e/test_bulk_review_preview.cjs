// Bulk "Review Results" split view: the ORIGINAL file is shown beside the extracted data and
// follows Previous / Next. Same shape as the other raw-Playwright scripts here: no runner, a
// `results` array of {step, ok, detail}, a SUMMARY at the end.
//
// Default (mock) mode needs only `npm run dev` in frontend (5174): the API is mocked with
// page.route (login state, bulk-upload, GET/PATCH documents), so no backend / OCR / DB is used.
// All 10 files are FAKE files generated into a temp dir - never real documents.
//
//   node test_bulk_review_preview.cjs
//
// LIVE=1 runs the same counter + SHA-256 checks against a real backend (started on a *_test
// database) with a real approved user and real OCR:
//   LIVE=1 E2E_USER_EMAIL=... E2E_USER_PASSWORD=... node test_bulk_review_preview.cjs
const { chromium } = require('playwright')
const crypto = require('crypto')
const fs = require('fs')
const os = require('os')
const path = require('path')

const BASE = 'http://localhost:5174'
const LIVE = process.env.LIVE === '1'
const SHOTS = process.env.SHOT_DIR || ''
const results = []
const consoleErrors = []

function log(step, ok, detail) {
  results.push({ step, ok, detail })
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`)
}

const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex')

// ---- fake file generation -------------------------------------------------------------------

function makePdf(text, padBytes = 0) {
  const parts = []
  const offsets = []
  let length = 0
  const push = (b) => { const buf = Buffer.isBuffer(b) ? b : Buffer.from(b, 'latin1'); parts.push(buf); length += buf.length }
  const obj = (n, body) => { offsets[n] = length; push(`${n} 0 obj\n${body}\nendobj\n`) }
  push('%PDF-1.4\n')
  obj(1, '<< /Type /Catalog /Pages 2 0 R >>')
  obj(2, '<< /Type /Pages /Kids [3 0 R] /Count 1 >>')
  obj(3, '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 420 220] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>')
  const content = `BT /F1 30 Tf 40 100 Td (${text}) Tj ET`
  obj(4, `<< /Length ${content.length} >>\nstream\n${content}\nendstream`)
  obj(5, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
  // an unreferenced object of random bytes: makes the file big and its hash unique
  const pad = crypto.randomBytes(padBytes || 64)
  offsets[6] = length
  push(`6 0 obj\n<< /Length ${pad.length} >>\nstream\n`)
  push(pad)
  push('\nendstream\nendobj\n')
  const xrefAt = length
  let xref = 'xref\n0 7\n0000000000 65535 f \n'
  for (let n = 1; n <= 6; n++) xref += `${String(offsets[n]).padStart(10, '0')} 00000 n \n`
  push(xref)
  push(`trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n${xrefAt}\n%%EOF\n`)
  return Buffer.concat(parts)
}

async function makePng(browser, text) {
  const p = await browser.newPage()
  const dataUrl = await p.evaluate((t) => {
    const c = document.createElement('canvas')
    c.width = 420; c.height = 220
    const g = c.getContext('2d')
    g.fillStyle = '#fff'; g.fillRect(0, 0, 420, 220)
    g.fillStyle = '#000'; g.font = 'bold 30px sans-serif'; g.fillText(t, 40, 110)
    return c.toDataURL('image/png')
  }, text)
  await p.close()
  return Buffer.from(dataUrl.split(',')[1], 'base64')
}

async function buildFakeFiles(browser) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ack-fake-'))
  fs.mkdirSync(path.join(dir, 'a'))
  fs.mkdirSync(path.join(dir, 'b'))
  const spec = [
    ['f01.pdf', 'pdf'], ['f02.pdf', 'pdf'], ['dup.pdf', 'pdf', 'a'], ['f04.pdf', 'pdf'], ['f05.pdf', 'pdf', null, 4.5 * 1024 * 1024],
    ['f06.pdf', 'pdf'], ['dup.pdf', 'pdf', 'b'], ['f08.pdf', 'pdf'], ['f09.png', 'png'], ['f10.png', 'png'],
  ]
  const files = []
  for (let i = 0; i < spec.length; i++) {
    const [name, kind, sub, pad] = spec[i]
    const label = `TEST FILE ${String(i + 1).padStart(2, '0')}`
    const buf = kind === 'pdf' ? makePdf(label, pad || 0) : await makePng(browser, label)
    const full = path.join(dir, sub || '', name)
    fs.writeFileSync(full, buf)
    files.push({ k: i + 1, name, path: full, sha: sha(buf), size: buf.length })
  }
  return { dir, files }
}

// ---- helpers --------------------------------------------------------------------------------

async function shownSha(page, expectIndex) {
  await page.waitForFunction(
    (idx) => {
      const w = document.querySelector('[data-testid=review-preview]')
      return w && w.getAttribute('data-index') === String(idx) && w.querySelector('embed, img')?.getAttribute('src')
    },
    expectIndex,
    { timeout: 10000 },
  )
  return page.evaluate(async () => {
    const el = document.querySelector('[data-testid=review-preview]').querySelector('embed, img')
    const buf = await (await fetch(el.getAttribute('src'))).arrayBuffer()
    const d = await crypto.subtle.digest('SHA-256', buf)
    return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, '0')).join('')
  })
}

const counter = (page) => page.locator('span', { hasText: /^\d+ of \d+$/ }).first().innerText()
const clickBtn = (page, name) => page.locator(`button:has-text("${name}")`).first().click()
const urlStats = (page) => page.evaluate(() => ({ ...window.__urlStats }))

;(async () => {
  const browser = await chromium.launch({ headless: true })
  const { dir, files } = await buildFakeFiles(browser)
  const context = await browser.newContext({ viewport: { width: 1360, height: 900 } })
  await context.addInitScript(() => {
    window.__urlStats = { created: 0, revoked: 0 }
    const c = URL.createObjectURL.bind(URL)
    const r = URL.revokeObjectURL.bind(URL)
    URL.createObjectURL = (o) => { window.__urlStats.created++; return c(o) }
    URL.revokeObjectURL = (u) => { window.__urlStats.revoked++; return r(u) }
  })
  const page = await context.newPage()
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 160)) })
  page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message.slice(0, 160)))

  const FAILED_ITEM = 4
  if (!LIVE) {
    await context.addInitScript(() => localStorage.setItem('ackintel_token', 'mock.jwt.token'))
    const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    const docFor = (k) => k === FAILED_ITEM
      ? { _id: `doc-${k}`, uploadStatus: 'failed', processingError: 'Mock OCR failure for this file' }
      : { _id: `doc-${k}`, uploadStatus: 'processed', taxInvoiceNo: `G00000000${k}`, referenceNo: `98000000${k}`, date: '01/01/2026', taxInvoiceNoConfidence: 100, referenceNoConfidence: 100, dateConfidence: 100, exported: false }
    // only the backend API - NOT Vite's own /src/api/*.js modules, which also contain "/api/"
    await page.route((u) => new URL(u).pathname.startsWith('/api/'), async (route) => {
      const req = route.request()
      const url = new URL(req.url())
      const p = url.pathname.replace(/^\/api/, '')
      const m = req.method()
      if (p === '/health') return json(route, { status: 'ok' })
      if (p === '/auth/me') return json(route, { user: { id: 'u1', username: 'mockuser', email: 'mock@looptest.local', role: 'user' } })
      if (p === '/documents/bulk-upload' && m === 'POST') {
        return json(route, { results: files.map((f) => ({ document: { _id: `doc-${f.k}` } })) }, 201)
      }
      let match = p.match(/^\/documents\/doc-(\d+)$/)
      if (match && m === 'GET') return json(route, { document: docFor(Number(match[1])) })
      match = p.match(/^\/documents\/doc-(\d+)\/correct$/)
      if (match && m === 'PATCH') {
        const body = JSON.parse(req.postData() || '{}')
        return json(route, { document: { ...docFor(Number(match[1])), [body.field]: body.value } })
      }
      return json(route, {})
    })
  }

  try {
    if (LIVE) {
      await page.goto(`${BASE}/login`)
      await page.fill('input[type=email]', process.env.E2E_USER_EMAIL)
      await page.fill('input[type=password]', process.env.E2E_USER_PASSWORD)
      await page.click('button[type=submit]')
      await page.waitForTimeout(2500)
    }
    await page.goto(`${BASE}/upload`)
    await page.waitForTimeout(1500)
    await page.click('button:has-text("Bulk Upload")')
    await page.setInputFiles('input[type=file]', files.map((f) => f.path))
    await page.waitForTimeout(800)
    log('setup: 10 fake files selected (8 PDF + 2 PNG, one ~4.5 MB, two named dup.pdf)', (await page.locator('select').count()) === 10 && files[4].size > 4.4 * 1024 * 1024, `5th file ${(files[4].size / 1048576).toFixed(2)} MB`)
    await page.click('button:has-text("Upload All")')
    await page.waitForSelector('text=Review Results', { timeout: LIVE ? 1500000 : 60000 })
    await page.waitForSelector('[data-testid=review-preview]', { timeout: 15000 })
    log('review screen reached, preview wrapper present', true)
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'review_1_desktop.png') })

    // ---- walk all 10 items --------------------------------------------------------------
    const stats0 = await urlStats(page)
    for (const f of files) {
      if (f.k > 1) await clickBtn(page, 'Next')
      const got = await shownSha(page, f.k - 1)
      const w = page.locator('[data-testid=review-preview]')
      const c = await counter(page)
      const okCounter = c === `${f.k} of 10`
      const okAttrs = (await w.getAttribute('data-filename')) === f.name && (await w.getAttribute('data-index')) === String(f.k - 1)
      log(`item ${f.k}: counter "${f.k} of 10", data-filename/index match`, okCounter && okAttrs, `counter="${c}" file=${await w.getAttribute('data-filename')}`)
      log(`item ${f.k}: SHA-256 of the shown file == source file ${f.name}`, got === f.sha, got ? got.slice(0, 12) : 'no preview')
      if (!LIVE && f.k === FAILED_ITEM) {
        const body = await page.locator('body').innerText()
        log('item 4 (failed): preview still shown and failure message visible', body.includes('Failed: Mock OCR failure') && !!got)
      }
      if (SHOTS && (f.k === 4 || f.k === 5)) await page.screenshot({ path: path.join(SHOTS, `review_item_${f.k}.png`) })
    }
    const afterWalk = await urlStats(page)
    log('object URLs: (created - revoked) <= 2 after walking all 10 items', afterWalk.created - afterWalk.revoked <= 2, `created=${afterWalk.created - stats0.created} revoked=${afterWalk.revoked - stats0.revoked} (+previous)`)
    log('Next disabled at 10', await page.locator('button:has-text("Next")').first().isDisabled())
    // ---- break tests --------------------------------------------------------------------
    const nextDisabled = await page.locator('button:has-text("Next")').first().isDisabled()
    for (let i = 9; i >= 1; i--) await clickBtn(page, 'Previous')
    log('Previous disabled at 1 (and counter "1 of 10")', (await page.locator('button:has-text("Previous")').first().isDisabled()) && (await counter(page)) === '1 of 10' && nextDisabled)

    // 30 rapid Next then 30 rapid Previous, no awaits between clicks
    await page.evaluate(() => {
      const click = (t) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === t)?.click()
      for (let i = 0; i < 30; i++) click('Next')
    })
    await page.waitForTimeout(400)
    const afterNext = await counter(page)
    const shaEnd = await shownSha(page, 9)
    log('30 rapid Next: counter "10 of 10", preview == file 10', afterNext === '10 of 10' && shaEnd === files[9].sha, afterNext)
    await page.evaluate(() => {
      const click = (t) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === t)?.click()
      for (let i = 0; i < 30; i++) click('Previous')
    })
    await page.waitForTimeout(400)
    const afterPrev = await counter(page)
    const shaStart = await shownSha(page, 0)
    log('30 rapid Previous: counter "1 of 10", preview == file 1', afterPrev === '1 of 10' && shaStart === files[0].sha, afterPrev)
    // interleaved fast clicks (one macrotask apart, i.e. faster than any human): net movement is
    // deterministic. 7 Next, 3 Previous, 2 Next from item 1 -> item 7.
    await page.evaluate(async () => {
      const click = (t) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === t)?.click()
      const tick = () => new Promise((r) => setTimeout(r, 0))
      for (let i = 0; i < 7; i++) { click('Next'); await tick() }
      for (let i = 0; i < 3; i++) { click('Previous'); await tick() }
      for (let i = 0; i < 2; i++) { click('Next'); await tick() }
    })
    await page.waitForTimeout(400)
    const mixed = await counter(page)
    log('interleaved rapid clicks end on the right item with the right preview', mixed === '7 of 10' && (await shownSha(page, 6)) === files[6].sha, mixed)
    const afterRapid = await urlStats(page)
    log('object URLs still balanced after 60+ rapid clicks (<= 2 alive)', afterRapid.created - afterRapid.revoked <= 2, `alive=${afterRapid.created - afterRapid.revoked}`)

    // ---- correction then Next (mock only: with real OCR of fake files an item may have no fields to edit)
    if (!LIVE) {
      for (let i = 0; i < 5; i++) await clickBtn(page, 'Previous') // item 7 -> item 2 (a processed one)
      await shownSha(page, 1)
      await page.locator('button:has-text("Edit")').first().click()
      await page.waitForTimeout(400)
      await page.locator('input[maxlength="40"]').fill('G999999999')
      await page.locator('button:has-text("Save")').last().click()
      await page.waitForTimeout(900)
      log('correction saved: item 2 still shows its own preview', (await shownSha(page, 1)) === files[1].sha && (await counter(page)) === '2 of 10')
      await clickBtn(page, 'Next')
      log('after the correction, Next shows item 3 with its own preview (not stale)', (await counter(page)) === '3 of 10' && (await shownSha(page, 2)) === files[2].sha)
      await clickBtn(page, 'Previous')
      log('back on item 2: preview still item 2', (await shownSha(page, 1)) === files[1].sha)
    }

    // ---- mobile layout ------------------------------------------------------------------
    await page.setViewportSize({ width: 390, height: 800 })
    await page.waitForTimeout(600)
    const m = await page.evaluate(() => {
      const w = document.querySelector('[data-testid=review-preview]').getBoundingClientRect()
      const prev = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Previous').getBoundingClientRect()
      const link = [...document.querySelectorAll('a')].find((a) => a.textContent.trim() === 'Open in new tab')
      const lr = link ? link.getBoundingClientRect() : null
      return { scrollW: document.documentElement.scrollWidth, innerW: window.innerWidth, previewTop: w.top + window.scrollY, prevTop: prev.top + window.scrollY, previewLeft: w.left, previewRight: w.right, linkVisible: !!lr && lr.width > 0 && lr.right <= window.innerWidth, linkTarget: link?.getAttribute('target'), linkRel: link?.getAttribute('rel'), linkHref: (link?.getAttribute('href') || '').slice(0, 5) }
    })
    log('390x800: no horizontal scroll', m.scrollW <= m.innerW, `scrollWidth=${m.scrollW} innerWidth=${m.innerW}`)
    log('390x800: stacked layout (preview sits below the data card, inside the screen)', m.previewTop > m.prevTop && m.previewLeft >= 0 && m.previewRight <= m.innerW + 1, `previewTop=${Math.round(m.previewTop)} prevBtnTop=${Math.round(m.prevTop)}`)
    log('390x800: "Open in new tab" visible, opens a new tab safely (blob:, _blank, noopener noreferrer)', m.linkVisible && m.linkTarget === '_blank' && /noopener/.test(m.linkRel || '') && /noreferrer/.test(m.linkRel || '') && m.linkHref === 'blob:', JSON.stringify({ t: m.linkTarget, r: m.linkRel, h: m.linkHref }))
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'review_2_mobile.png'), fullPage: true })
    await page.setViewportSize({ width: 1360, height: 900 })
    await page.waitForTimeout(400)
    const wide = await page.evaluate(() => {
      const w = document.querySelector('[data-testid=review-preview]').getBoundingClientRect()
      const prev = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Previous').getBoundingClientRect()
      return { previewLeft: w.left, prevLeft: prev.left, sameRow: Math.abs(w.top - prev.top) < 700 }
    })
    log('1360 wide: split view (preview is to the RIGHT of the data card)', wide.previewLeft > wide.prevLeft + 200, JSON.stringify(wide))

    // ---- single upload mode unchanged ---------------------------------------------------
    await clickBtn(page, 'Start New Batch')
    await page.waitForTimeout(500)
    await page.locator('button:has-text("Single Upload")').click()
    await page.setInputFiles('input[type=file]', files[0].path)
    await page.waitForSelector('embed', { timeout: 8000 })
    log('Single Upload: selecting a file still shows its preview', (await page.locator('embed').count()) === 1)
    log('Single Upload: preview has no review test id and no "Open in new tab" (unchanged)', (await page.locator('[data-testid=review-preview]').count()) === 0 && (await page.locator('a:has-text("Open in new tab")').count()) === 0)
  } catch (err) {
    log('RUNNER', false, err.message.split('\n')[0])
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'review_ERROR.png') }).catch(() => {})
  } finally {
    log('console: zero errors during the whole run', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '))
    await browser.close()
    fs.rmSync(dir, { recursive: true, force: true })
  }

  const failed = results.filter((r) => !r.ok)
  console.log('\n=== SUMMARY ===')
  console.log(`${results.length - failed.length}/${results.length} passed${LIVE ? ' (LIVE)' : ' (mock)'}`)
  failed.forEach((f) => console.log(`FAILED: ${f.step} - ${f.detail || ''}`))
  if (SHOTS) fs.writeFileSync(path.join(SHOTS, LIVE ? 'review_live_results.json' : 'review_mock_results.json'), JSON.stringify(results, null, 1))
  process.exit(failed.length ? 1 : 0)
})()
