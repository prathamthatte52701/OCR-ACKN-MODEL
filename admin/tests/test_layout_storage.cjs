// Plain Node check (no runner): node admin/tests/test_layout_storage.cjs
// Override the module under test with LAYOUT_STORAGE_PATH=<abs path to layoutStorage.js>.
const assert = require('node:assert/strict')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

const EXPECTED_KEY = 'ackn.admin.sidebarHidden'
const OTHER_APP_KEY = 'ackn.user.sidebarHidden'

const fake = (init = {}) => {
  const m = new Map(Object.entries(init))
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => void m.set(k, String(v)),
    removeItem: (k) => void m.delete(k),
    _m: m,
  }
}
const throwing = (which) => ({
  getItem: () => { if (which === 'get') throw new Error('blocked'); return null },
  setItem: () => { if (which === 'set') throw new Error('QuotaExceededError') },
  removeItem: () => {},
})

;(async () => {
  const file = process.env.LAYOUT_STORAGE_PATH
    || path.join(__dirname, '..', 'src', 'utils', 'layoutStorage.js')
  let mod
  try {
    mod = await import(pathToFileURL(file).href)
  } catch (e) {
    // a renamed file or a syntax error must FAIL the test; skipping is opt-in only
    if (process.env.ALLOW_SKIP) { console.log(`SKIP: cannot load ${file}: ${e.message}`); return }
    console.error(`FAIL: cannot load ${file}: ${e.message}`)
    process.exit(1)
  }
  const { SIDEBAR_HIDDEN_KEY, readSidebarHidden, writeSidebarHidden, nextSidebarHidden, toggleAndPersist } = mod

  // key
  assert.equal(SIDEBAR_HIDDEN_KEY, EXPECTED_KEY)
  assert.notEqual(SIDEBAR_HIDDEN_KEY, OTHER_APP_KEY)

  // read: default / valid
  assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, fake()), false)
  assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, fake({ [EXPECTED_KEY]: 'true' })), true)
  assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, fake({ [EXPECTED_KEY]: 'false' })), false)
  // default key is used when key omitted
  assert.equal(readSidebarHidden(undefined, fake({ [EXPECTED_KEY]: 'true' })), true)

  // read: garbage
  const garbage = ['1', 'yes', 'TRUE', ' true', 'true ', '{"a":1}', 'null', '', 'x'.repeat(100000), 1, true, {}, [], undefined]
  for (const g of garbage) {
    const s = { getItem: () => g, setItem() {}, removeItem() {} }
    assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, s), false, `garbage ${String(g).slice(0, 20)}`)
  }

  // throwing storage
  assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, throwing('get')), false)
  assert.equal(writeSidebarHidden(true, SIDEBAR_HIDDEN_KEY, throwing('set')), false)
  assert.equal(writeSidebarHidden(false, SIDEBAR_HIDDEN_KEY, throwing('set')), false)

  // no storage at all (Node has no localStorage)
  assert.equal(globalThis.localStorage, undefined)
  for (const s of [undefined, null]) {
    assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, s), false)
    assert.equal(writeSidebarHidden(true, SIDEBAR_HIDDEN_KEY, s), false)
  }
  assert.equal(readSidebarHidden(), false)
  assert.equal(writeSidebarHidden(true), false)

  // localStorage getter that throws
  Object.defineProperty(globalThis, 'localStorage', { get() { throw new Error('blocked') }, configurable: true })
  try {
    assert.equal(readSidebarHidden(), false)
    assert.equal(writeSidebarHidden(true), false)
  } finally {
    delete globalThis.localStorage
  }

  // default storage resolves to globalThis.localStorage lazily
  const g = fake()
  globalThis.localStorage = g
  try {
    assert.equal(writeSidebarHidden(true), true)
    assert.equal(g._m.get(EXPECTED_KEY), 'true')
    assert.equal(readSidebarHidden(), true)
  } finally {
    delete globalThis.localStorage
  }

  // round trip
  const st = fake()
  assert.equal(writeSidebarHidden(true, SIDEBAR_HIDDEN_KEY, st), true)
  assert.equal(st._m.get(EXPECTED_KEY), 'true')
  assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, st), true)
  assert.equal(writeSidebarHidden(false, SIDEBAR_HIDDEN_KEY, st), true)
  assert.equal(st._m.get(EXPECTED_KEY), 'false')
  assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, st), false)
  // custom key is isolated
  writeSidebarHidden(true, 'other', st)
  assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, st), false)
  assert.equal(readSidebarHidden('other', st), true)

  // next
  assert.equal(nextSidebarHidden(false), true)
  assert.equal(nextSidebarHidden(true), false)
  assert.equal(nextSidebarHidden(nextSidebarHidden(false)), false)
  assert.equal(nextSidebarHidden(0), true)
  assert.equal(nextSidebarHidden(''), true)
  assert.equal(nextSidebarHidden(null), true)
  assert.equal(nextSidebarHidden(undefined), true)
  assert.equal(nextSidebarHidden('x'), false)
  assert.equal(nextSidebarHidden(1), false)

  // rapid toggling
  let cur = false
  const rs = fake()
  for (let i = 0; i < 1000; i++) {
    cur = nextSidebarHidden(cur)
    writeSidebarHidden(cur, SIDEBAR_HIDDEN_KEY, rs)
  }
  assert.equal(cur, false)
  assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, rs), false)
  cur = nextSidebarHidden(cur)
  writeSidebarHidden(cur, SIDEBAR_HIDDEN_KEY, rs)
  assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, rs), true)

  // toggleAndPersist: writes synchronously, no render/effect involved
  const tp = fake()
  const ref = { current: false }
  assert.equal(toggleAndPersist(ref, SIDEBAR_HIDDEN_KEY, tp), true)
  assert.equal(ref.current, true)
  assert.equal(tp._m.get(EXPECTED_KEY), 'true') // already persisted
  assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, tp), ref.current)
  // two quick toggles end consistent
  assert.equal(toggleAndPersist(ref, SIDEBAR_HIDDEN_KEY, tp), false)
  assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, tp), ref.current)
  assert.equal(toggleAndPersist(ref, SIDEBAR_HIDDEN_KEY, tp), true)
  assert.equal(toggleAndPersist(ref, SIDEBAR_HIDDEN_KEY, tp), false)
  assert.equal(readSidebarHidden(SIDEBAR_HIDDEN_KEY, tp), false)
  // throwing storage: no throw, ref still flips
  const tref = { current: false }
  assert.equal(toggleAndPersist(tref, SIDEBAR_HIDDEN_KEY, throwing('set')), true)
  assert.equal(tref.current, true)
  assert.equal(toggleAndPersist(tref, SIDEBAR_HIDDEN_KEY, throwing('set')), false)
  assert.equal(tref.current, false)
  // default key + global localStorage
  globalThis.localStorage = fake()
  try {
    const dref = { current: false }
    toggleAndPersist(dref)
    assert.equal(globalThis.localStorage._m.get(EXPECTED_KEY), 'true')
  } finally {
    delete globalThis.localStorage
  }

  // chat panel flag: same helpers, own key; the sidebar flag is untouched
  const { CHAT_OPEN_KEY, chatUserKey, readStored, writeStored, removeStored, removeChatUserKeys } = mod
  assert.equal(CHAT_OPEN_KEY, 'ackn.admin.chatOpen')
  const cs = fake()
  assert.equal(readSidebarHidden(CHAT_OPEN_KEY, cs), false)
  assert.equal(toggleAndPersist({ current: false }, CHAT_OPEN_KEY, cs), true)
  assert.equal(cs._m.get(CHAT_OPEN_KEY), 'true')
  assert.equal(cs._m.has(SIDEBAR_HIDDEN_KEY), false)
  assert.equal(readSidebarHidden(CHAT_OPEN_KEY, throwing('get')), false)

  // remembered chat user, per admin id; logout removes every admin's entry
  const withKeys = (init) => {
    const st = fake(init)
    st.key = (i) => [...st._m.keys()][i] ?? null
    Object.defineProperty(st, 'length', { get: () => st._m.size })
    return st
  }
  assert.equal(chatUserKey('a1'), 'ackn.admin.chatUser.a1')
  assert.notEqual(chatUserKey('a1'), chatUserKey('a2'))
  const us = withKeys({ [SIDEBAR_HIDDEN_KEY]: 'true', [CHAT_OPEN_KEY]: 'true' })
  assert.equal(readStored(chatUserKey('a1'), us), null)
  assert.equal(writeStored(chatUserKey('a1'), 'u9', us), true)
  assert.equal(writeStored(chatUserKey('a2'), 'u7', us), true)
  assert.equal(readStored(chatUserKey('a1'), us), 'u9')
  assert.equal(readStored(chatUserKey('a2'), us), 'u7') // another admin has their own entry
  assert.equal(removeChatUserKeys(us), 3) // both remembered users and the open-panel flag
  assert.equal(readStored(chatUserKey('a1'), us), null)
  assert.equal(readStored(chatUserKey('a2'), us), null)
  assert.equal(us._m.get(SIDEBAR_HIDDEN_KEY), 'true') // unrelated keys stay
  assert.equal(us._m.has(CHAT_OPEN_KEY), false) // the next admin does not inherit an open panel
  assert.equal(removeChatUserKeys(us), 0)
  assert.equal(removeChatUserKeys(undefined), 0) // no storage in Node: no throw
  writeStored(chatUserKey('a1'), 'u9', us)
  removeStored(chatUserKey('a1'), us)
  assert.equal(readStored(chatUserKey('a1'), us), null)
  assert.doesNotThrow(() => removeStored('x', throwing('get')))
  assert.doesNotThrow(() => removeStored('x'))
  assert.equal(readStored('x', throwing('get')), null)
  assert.equal(writeStored('x', 'y', throwing('set')), false)

  console.log('OK: layoutStorage (admin app)')
})().catch((e) => {
  console.error('FAIL:', e.message)
  process.exit(1)
})
