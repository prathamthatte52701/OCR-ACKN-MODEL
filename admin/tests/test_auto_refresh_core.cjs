// Plain Node check (no runner): node admin/tests/test_auto_refresh_core.cjs
// Imports the REAL src/utils/autoRefreshCore.js - there is no second copy of the rules.
const assert = require('node:assert/strict')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

;(async () => {
  assert.equal(typeof window, 'undefined')
  assert.equal(typeof document, 'undefined')
  const core = await import(pathToFileURL(path.join(__dirname, '..', 'src', 'utils', 'autoRefreshCore.js')).href)
  const idle = { visible: true, now: 100000 }
  const tests = []
  const test = (name, fn) => tests.push([name, fn])

  test('runs when visible, idle and free', () => {
    assert.equal(core.shouldRun(core.createState(), idle), true)
  })
  test('skipped when the tab is hidden', () => {
    assert.equal(core.shouldRun(core.createState(), { ...idle, visible: false }), false)
  })
  test('skipped while a refresh is in flight, runs again after it finishes', () => {
    const s = core.createState()
    core.markStarted(s, 1000)
    assert.equal(core.shouldRun(s, idle), false)
    core.markFinished(s)
    assert.equal(core.shouldRun(s, idle), true)
  })
  test('skipped while the page is busy', () => {
    assert.equal(core.shouldRun(core.createState(), { ...idle, busy: true }), false)
  })
  test('skipped while a modal is open', () => {
    assert.equal(core.shouldRun(core.createState(), { ...idle, modalOpen: true }), false)
  })
  test('minInterval respected', () => {
    const s = core.createState()
    core.markStarted(s, 100000)
    core.markFinished(s)
    assert.equal(core.shouldRun(s, { visible: true, now: 130000, minIntervalMs: 60000 }), false)
    assert.equal(core.shouldRun(s, { visible: true, now: 160000, minIntervalMs: 60000 }), true)
  })
  test('focus/visible beat allowed once per 5 s', () => {
    const s = core.createState()
    assert.equal(core.allowFocusBeat(s, 10000), true)
    assert.equal(core.allowFocusBeat(s, 12000), false)
    assert.equal(core.allowFocusBeat(s, 14999), false)
    assert.equal(core.allowFocusBeat(s, 15000), true)
  })
  test('stale after a local change (markChanged)', () => {
    const s = core.createState()
    const start = core.markStarted(s, 0)
    assert.equal(core.isStale(s, start.mutation, start.requestId), false)
    core.bumpMutation(s)
    assert.equal(core.isStale(s, start.mutation, start.requestId), true)
  })
  test('stale after a newer load started', () => {
    const s = core.createState()
    const start = core.markStarted(s, 0)
    assert.equal(core.bumpRequest(s), 1)
    assert.equal(core.isStale(s, start.mutation, start.requestId), true)
  })
  test('a load that started before the refresh does not make it stale', () => {
    const s = core.createState()
    core.bumpRequest(s)
    const start = core.markStarted(s, 0)
    assert.equal(core.isStale(s, start.mutation, start.requestId), false)
  })
  test('sameRows: identical data is the same', () => {
    const a = [{ id: '1', status: 'pending', updatedAt: 'x' }, { id: '2', status: 'approved', updatedAt: 'y' }]
    const b = a.map((r) => ({ ...r }))
    assert.equal(core.sameRows(a, b, ['status', 'updatedAt']), true)
  })
  test('sameRows: one status or updatedAt differing, a new row or other order is a change', () => {
    const a = [{ id: '1', status: 'pending', updatedAt: 'x' }, { id: '2', status: 'approved', updatedAt: 'y' }]
    const keys = ['status', 'updatedAt']
    assert.equal(core.sameRows(a, [a[0], { ...a[1], status: 'rejected' }], keys), false)
    assert.equal(core.sameRows(a, [a[0], { ...a[1], updatedAt: 'z' }], keys), false)
    assert.equal(core.sameRows(a, [a[0]], keys), false)
    assert.equal(core.sameRows(a, [a[1], a[0]], keys), false)
    assert.equal(core.sameRows(null, a, keys), false)
  })
  test('clampPage', () => {
    assert.equal(core.clampPage(3, 2), 2)
    assert.equal(core.clampPage(2, 5), 2)
    assert.equal(core.clampPage(0, 5), 1)
    assert.equal(core.clampPage(4, 0), 1)
  })
  test('3 failures back off 4 beats, then recover', () => {
    const s = core.createState()
    core.recordFailure(s, 500)
    core.recordFailure(s, undefined)
    assert.equal(core.shouldRun(s, idle), true)
    core.recordFailure(s, 500)
    for (let i = 0; i < 4; i++) assert.equal(core.shouldRun(s, idle), false)
    assert.equal(core.shouldRun(s, idle), true)
  })
  test('a success resets the failure count', () => {
    const s = core.createState()
    core.recordFailure(s, 500)
    core.recordFailure(s, 500)
    core.recordSuccess(s)
    core.recordFailure(s, 500)
    assert.equal(core.shouldRun(s, idle), true)
  })
  test('a single 429 backs off 4 beats, then recovers', () => {
    const s = core.createState()
    core.recordFailure(s, 429)
    for (let i = 0; i < 4; i++) assert.equal(core.shouldRun(s, idle), false)
    assert.equal(core.shouldRun(s, idle), true)
  })
  test('resetBackoff ends a backoff at once (backend came back)', () => {
    const s = core.createState()
    core.recordFailure(s, 429)
    core.resetBackoff(s)
    assert.equal(core.shouldRun(s, idle), true)
  })
  test('hidden or busy beats do not use up the backoff', () => {
    const s = core.createState()
    core.recordFailure(s, 429)
    assert.equal(core.shouldRun(s, { ...idle, visible: false }), false)
    assert.equal(core.shouldRun(s, { ...idle, busy: true }), false)
    for (let i = 0; i < 4; i++) assert.equal(core.shouldRun(s, idle), false)
    assert.equal(core.shouldRun(s, idle), true)
  })

  let failed = 0
  for (const [name, fn] of tests) {
    try {
      fn()
      console.log(`  ok   ${name}`)
    } catch (err) {
      failed += 1
      console.log(`  FAIL ${name}\n       ${err.message}`)
    }
  }
  if (failed) {
    console.log(`FAILED: ${failed} of ${tests.length}`)
    process.exit(1)
  }
  console.log(`OK: autoRefreshCore (${tests.length} tests)`)
})()
