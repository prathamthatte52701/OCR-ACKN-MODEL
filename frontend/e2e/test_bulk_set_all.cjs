// Bulk Upload "Set all as" control. Same shape as the other raw-Playwright scripts here:
// no runner, a `results` array, a SUMMARY at the end.
//
// Needs: backend on a *_test database, `npm run dev` in frontend (5174), and an APPROVED
// user in that database:
//   E2E_USER_EMAIL=... E2E_USER_PASSWORD=... [SHOT_DIR=...] node test_bulk_set_all.cjs
// The last case really uploads 10 files (real OCR, ~3 minutes).
const { chromium } = require('playwright')
const fs = require('fs')

const BASE = 'http://localhost:5174'
const API = 'http://127.0.0.1:8000/api'
const EMAIL = process.env.E2E_USER_EMAIL
const PASSWORD = process.env.E2E_USER_PASSWORD
const SHOTS = process.env.SHOT_DIR || '.'
const TI = 'Tax Invoice'
const DC = 'Delivery Challan'
const DC_DIR = 'E:/ackn testing data/delivery challan test doc/'
const TI_DIR = 'E:/ackn testing data/tax invoice test doc/'
const TEN = Array.from({ length: 10 }, (_, i) => `${DC_DIR}${i + 1}-D.pdf`)
const results = []

function log(step, ok, detail) {
  results.push({ step, ok, detail })
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${step}${detail ? ' - ' + detail : ''}`)
}

;(async () => {
  const browser = await chromium.launch({ headless: true })
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 1000 } })).newPage()
  const uploads = [] // every request to an upload endpoint (the control must never cause one)
  page.on('request', (r) => { if (/\/documents\/(bulk-)?upload/.test(r.url()) && r.method() === 'POST') uploads.push(r) })

  const group = () => page.locator('[role=group][aria-label="Set all as"]')
  const btn = (t) => group().locator(`button:has-text("${t}")`)
  const rows = () => page.locator('select')
  const types = async () => page.$$eval('select', (els) => els.map((e) => e.value))
  const allAre = async (t, n) => { const v = await types(); return v.length === n && v.every((x) => x === t) }
  const pressed = async (t) => (await btn(t).getAttribute('aria-pressed')) === 'true'
  const mixedShown = async () => (await group().locator('text=Mixed').count()) === 1
  const pick = async (files) => { await page.setInputFiles('input[type=file]', files); await page.waitForTimeout(500) }
  const removeAll = async () => { while ((await page.locator('button:has-text("Remove")').count()) > 0) await page.locator('button:has-text("Remove")').first().click() }

  try {
    await page.goto(`${BASE}/login`)
    await page.fill('input[type=email]', EMAIL)
    await page.fill('input[type=password]', PASSWORD)
    await page.click('button[type=submit]')
    await page.waitForTimeout(2500)
    await page.goto(`${BASE}/upload`)
    await page.waitForTimeout(1500)
    await page.click('button:has-text("Bulk Upload")')
    await page.waitForTimeout(500)

    // 0. nothing selected -> control hidden
    log('0 no files -> control hidden', (await group().count()) === 0)

    // 1. defaults
    await pick(TEN)
    log('1 10 files selected: control visible, every row Tax Invoice (as today)', (await group().count()) === 1 && (await rows().count()) === 10 && (await allAre(TI, 10)))
    log('1b Tax Invoice button highlighted, no "Mixed"', (await pressed(TI)) && !(await pressed(DC)) && !(await mixedShown()))
    await page.screenshot({ path: `${SHOTS}/set_all_1_default.png` })

    // 2. Set all Delivery Challan
    await btn(DC).click()
    log('2 click Delivery Challan -> all 10 rows Delivery Challan', await allAre(DC, 10), JSON.stringify((await types()).slice(0, 3)))
    log('2b Delivery Challan highlighted, Tax Invoice not', (await pressed(DC)) && !(await pressed(TI)) && !(await mixedShown()))
    await page.screenshot({ path: `${SHOTS}/set_all_2_dc.png` })

    // 3. flip back
    await btn(TI).click()
    log('3 click Tax Invoice -> all 10 flip back', (await allAre(TI, 10)) && (await pressed(TI)))

    // 4. one exception by hand -> Mixed
    await rows().nth(4).selectOption(DC)
    log('4 change one row by hand -> "Mixed" shown, neither button highlighted', (await mixedShown()) && !(await pressed(TI)) && !(await pressed(DC)), JSON.stringify(await types()))
    await page.screenshot({ path: `${SHOTS}/set_all_3_mixed.png` })
    log('4b the manual change only touched that one row', (await types()).filter((t) => t === DC).length === 1)

    // 5. set all again clears mixed
    await btn(DC).click()
    log('5 Set all again -> mixed clears, all Delivery Challan', (await allAre(DC, 10)) && !(await mixedShown()) && (await pressed(DC)))

    // 6. removing a file keeps the state right
    await page.locator('button:has-text("Remove")').nth(2).click()
    log('6 remove one file -> 9 rows, still all Delivery Challan', (await allAre(DC, 9)) && (await pressed(DC)))
    await rows().nth(0).selectOption(TI)
    await page.locator('button:has-text("Remove")').nth(0).click() // remove the odd one out
    log('6b removing the only odd row clears "Mixed"', (await allAre(DC, 8)) && !(await mixedShown()))

    // 7. remove until 0 -> hidden
    await removeAll()
    log('7 remove files until 0 -> control hidden, no rows', (await group().count()) === 0 && (await rows().count()) === 0)

    // 8. files added after Set all follow the last choice (Delivery Challan), also after removing everything
    await pick(TEN.slice(0, 3))
    log('8a re-adding after removing everything: control back, new rows follow the last choice (Delivery Challan)', (await group().count()) === 1 && (await allAre(DC, 3)))
    await btn(TI).click()
    await pick(TEN.slice(3, 5)) // a second selection adds to the list (existing behaviour)
    log('8b Set all Tax Invoice, then add 2 more files -> 5 rows all Tax Invoice', await allAre(TI, 5), JSON.stringify(await types()))
    log('8c after manual exception the next added file still takes the last Set-all type', await (async () => {
      await rows().nth(0).selectOption(DC)
      await pick([TEN[5]])
      const v = await types()
      return v.length === 6 && v[0] === DC && v[5] === TI && (await mixedShown())
    })())

    // 9. break tests
    await removeAll()
    await pick([...TEN, `${TI_DIR}1-T.pdf`])
    const errText = await page.locator('body').innerText()
    log('9a 11 files at once -> rejected with the limit message, list unchanged', errText.includes('maximum of 10') && (await rows().count()) === 0, `rows=${await rows().count()}`)
    await pick(TEN.slice(0, 6))
    await pick(TEN.slice(6, 10).concat([`${TI_DIR}1-T.pdf`])) // 6 + 5 = 11
    log('9b adding past 10 (6 + 5) -> rejected, still 6 rows', (await page.locator('body').innerText()).includes('maximum of 10') && (await rows().count()) === 6)
    await btn(DC).dblclick()
    await btn(DC).click({ clickCount: 3 })
    await btn(TI).dblclick()
    log('9c rapid double / triple clicks -> consistent state (all Tax Invoice), no error', (await allAre(TI, 6)) && (await pressed(TI)))
    await page.locator('button:has-text("Single Upload")').click()
    await page.waitForTimeout(400)
    log('9d switching to Single hides the bulk control', (await group().count()) === 0)
    await page.locator('button:has-text("Bulk Upload")').click()
    await page.waitForTimeout(400)
    log('9e back on Bulk: the list and the control state are still there', (await group().count()) === 1 && (await rows().count()) === 6 && (await allAre(TI, 6)))
    await btn(DC).click()
    await page.locator('button:has-text("Single Upload")').click()
    await page.locator('button:has-text("Bulk Upload")').click()
    log('9f Set all, tab away and back -> still Delivery Challan', (await allAre(DC, 6)) && (await pressed(DC)))
    log('9g none of the clicks above sent an upload request', uploads.length === 0, `requests=${uploads.length}`)
    await removeAll()

    // 10. the real upload: Set all as Delivery Challan, upload 10, check what was saved
    await pick(TEN)
    await btn(TI).click()
    await btn(DC).click()
    log('10a 10 files, Set all as Delivery Challan', await allAre(DC, 10))
    // record exactly what the app appends to the upload FormData (the request itself is not
    // touched, so the upload behaves as in real use)
    await page.evaluate(() => {
      window.__fd = []
      const orig = FormData.prototype.append
      FormData.prototype.append = function (key, value, ...rest) {
        window.__fd.push([key, typeof value === 'string' ? value : `file:${value.name}`])
        return orig.call(this, key, value, ...rest)
      }
    })
    await page.click('button:has-text("Upload All")')
    await page.waitForTimeout(2500)
    const sent = await page.evaluate(() => window.__fd)
    const fileParts = sent.filter(([k]) => k === 'documents').length
    const typeValues = sent.filter(([k]) => k === 'documentTypes').map(([, v]) => v)
    const strangeKeys = sent.filter(([k]) => k !== 'documents' && k !== 'documentTypes').length
    log(
      '10b request format unchanged: 10 "documents" + 10 "documentTypes" (all Delivery Challan), no other fields',
      fileParts === 10 && typeValues.length === 10 && typeValues.every((v) => v === DC) && strangeKeys === 0,
      `documents=${fileParts} documentTypes=${typeValues.length} other=${strangeKeys}`,
    )
    // Wait on the SERVER's own status, not the page's progress text: the page stops polling after
    // a fixed number of tries (BULK_POLL_MAX_ATTEMPTS) and then reports the rest as "taking
    // longer than expected", which says nothing about the documents themselves.
    const token = await page.evaluate(() => (Object.values(localStorage).join(' ').match(/eyJ[\w-]+\.[\w-]+\.[\w-]+/) || [''])[0])
    // the server is busy with OCR (one document at a time), so a request can time out or be
    // reset now and then - retry instead of failing the run
    const fetchDocs = async () => {
      for (let attempt = 0; attempt < 12; attempt++) {
        try {
          return (await (await page.request.get(`${API}/documents?page=1&limit=30`, { headers: { Authorization: 'Bearer ' + token }, timeout: 60000 })).json()).documents || []
        } catch (e) {
          await page.waitForTimeout(5000)
        }
      }
      throw new Error('server did not answer the documents list after 12 tries')
    }
    let saved = await fetchDocs()
    for (let i = 0; i < 120 && saved.some((d) => d.uploadStatus === 'uploaded'); i++) {
      await page.waitForTimeout(10000)
      saved = await fetchDocs()
    }
    await page.screenshot({ path: `${SHOTS}/set_all_4_uploaded.png` })
    log('10c all 10 documents finished processing on the server', saved.length === 10 && saved.every((d) => d.uploadStatus === 'processed'), JSON.stringify(saved.reduce((acc, d) => ({ ...acc, [d.uploadStatus]: (acc[d.uploadStatus] || 0) + 1 }), {})))
    log('10d all 10 saved documents have documentType "Delivery Challan"', saved.length === 10 && saved.every((d) => d.documentType === DC), `${saved.length} docs, types=${[...new Set(saved.map((d) => d.documentType))].join(',')}`)
  } catch (err) {
    log('RUNNER', false, err.message.split('\n')[0])
    await page.screenshot({ path: `${SHOTS}/set_all_ERROR.png` }).catch(() => {})
  } finally {
    await browser.close()
  }

  const failed = results.filter((r) => !r.ok)
  console.log('\n=== SUMMARY ===')
  console.log(`${results.length - failed.length}/${results.length} passed`)
  failed.forEach((f) => console.log(`FAILED: ${f.step} - ${f.detail || ''}`))
  fs.writeFileSync(`${SHOTS}/set_all_results.json`, JSON.stringify(results, null, 1))
  process.exit(failed.length ? 1 : 0)
})()
