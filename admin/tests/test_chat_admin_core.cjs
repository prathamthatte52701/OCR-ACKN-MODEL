// Plain Node check (no runner): node admin/tests/test_chat_admin_core.cjs
const assert = require('node:assert/strict')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

const load = (rel) => import(pathToFileURL(path.join(__dirname, '..', 'src', rel)).href)
const thread = (userId, unreadCount = 0, name = userId) => ({ userId, name, unreadCount, lastMessageAt: null })

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const lin = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}
const contrast = (fg, bg) => {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

;(async () => {
  assert.equal(typeof window, 'undefined')
  const core = await load('utils/chatAdminCore.js')
  const { unreadTotal, overlayUnread, pickSelected, badgeText, clearSummary, isTyped, filterThreads, createTokens, CLEAR_RANGES } = core

  // unreadTotal
  assert.equal(unreadTotal([]), 0)
  assert.equal(unreadTotal(undefined), 0)
  assert.equal(unreadTotal([{ userId: 'a', count: 2 }, { userId: 'b', count: 3 }]), 5)

  // overlayUnread: the loaded counts win; users missing from them have none
  const ts = [thread('a', 5), thread('b', 0), thread('c', 1)]
  assert.equal(overlayUnread(ts, null), ts)
  assert.deepEqual(overlayUnread(ts, [{ userId: 'b', count: 4 }]).map((t) => t.unreadCount), [0, 4, 0])
  assert.deepEqual(overlayUnread(ts, []).map((t) => t.unreadCount), [0, 0, 0])
  assert.equal(ts[0].unreadCount, 5) // input untouched
  assert.deepEqual(overlayUnread([], [{ userId: 'x', count: 1 }]), [])

  // pickSelected
  assert.equal(pickSelected([], 'a'), null)
  assert.equal(pickSelected([thread('a'), thread('b')], 'b'), 'b') // stored and present
  assert.equal(pickSelected([thread('a'), thread('b', 2)], 'gone'), 'b') // stored missing -> first unread
  assert.equal(pickSelected([thread('a'), thread('b', 2)], null), 'b')
  assert.equal(pickSelected([thread('a'), thread('b')], null), 'a') // none unread -> first
  assert.equal(pickSelected([thread('a'), thread('b', 1)], 'a'), 'a') // stored wins over unread

  // unreadForAdmin: only user messages addressed to THIS admin, not yet read
  const { unreadForAdmin } = core
  const um = (id, to, readAt = null) => ({ id, fromRole: 'user', toAdminId: to, readAt })
  const msgs = [um('1', 'A'), um('2', 'B'), um('3', 'A', '2026-10-01T10:00:00Z'), { id: '4', fromRole: 'admin', toAdminId: null, readAt: null }]
  assert.deepEqual(unreadForAdmin(msgs, 'A').map((m) => m.id), ['1'])
  assert.deepEqual(unreadForAdmin(msgs, 'B').map((m) => m.id), ['2']) // each admin has their own unread
  assert.deepEqual(unreadForAdmin(msgs, 'C'), [])
  assert.deepEqual(unreadForAdmin([], 'A'), [])

  // badgeText
  assert.equal(badgeText(0), '')
  assert.equal(badgeText(-3), '')
  assert.equal(badgeText(undefined), '')
  assert.equal(badgeText(1), '1')
  assert.equal(badgeText(99), '99')
  assert.equal(badgeText(100), '99+')
  assert.equal(badgeText(5000), '99+')

  // clearSummary
  assert.equal(clearSummary('1w', 0), 'No messages match this range.')
  assert.equal(clearSummary('1w', 1), '1 message will be deleted (older than 1 week)')
  assert.equal(clearSummary('3m', 12), '12 messages will be deleted (older than 3 months)')
  assert.equal(clearSummary('all', 7), '7 messages will be deleted (all messages)')
  assert.equal(clearSummary('all', 7, 1), '7 messages and 1 file will be deleted (all messages)')
  assert.equal(clearSummary('1w', 2, 3), '2 messages and 3 files will be deleted (older than 1 week)')
  assert.equal(core.filesPart(0), '')
  assert.equal(core.filesPart(2), ' and 2 files')
  assert.deepEqual(CLEAR_RANGES.map((r) => r.id), ['24h', '3d', '1w', '1m', '3m', '6m', '1y', 'all'])

  // isTyped: exact, case-sensitive, no trim
  assert.equal(isTyped('DELETE'), true)
  for (const bad of ['delete', 'Delete', 'DELETE ', ' DELETE', 'DELET', 'DELETEE', '', 'DELETE\n', undefined, null]) {
    assert.equal(isTyped(bad), false, JSON.stringify(bad))
  }

  // describeGlobalClearError
  const { describeGlobalClearError } = core
  const http = (status, userMessage) => ({ response: { status }, userMessage })
  assert.equal(describeGlobalClearError(http(400, 'Incorrect password.')), 'Incorrect password.')
  const google = "This account uses Google Sign-In - there's no password to confirm with."
  assert.equal(describeGlobalClearError(http(400, google)), google)
  assert.equal(describeGlobalClearError(http(429, 'Too many requests. Please try again later.')), 'Too many tries. Try again in an hour.')
  assert.equal(describeGlobalClearError({ message: 'Network Error' }), 'Could not reach the server. Nothing was deleted.')
  assert.equal(describeGlobalClearError(http(500, undefined)), 'Could not delete the messages. Nothing was deleted.')

  // filterThreads
  const named = [thread('1', 0, 'Alice'), thread('2', 0, 'bob'), thread('3', 0, 'Carol')]
  assert.equal(filterThreads(named, '').length, 3)
  assert.equal(filterThreads(named, '  ').length, 3)
  assert.deepEqual(filterThreads(named, 'AL').map((t) => t.userId), ['1'])
  assert.deepEqual(filterThreads(named, 'o').map((t) => t.userId), ['2', '3'])
  assert.equal(filterThreads(named, 'zzz').length, 0)

  // createTokens: only the newest request is current
  const tokens = createTokens()
  const first = tokens.next()
  assert.equal(tokens.isCurrent(first), true)
  const second = tokens.next()
  assert.equal(tokens.isCurrent(first), false) // a slow old answer is dropped
  assert.equal(tokens.isCurrent(second), true)
  assert.equal(tokens.isCurrent(undefined), false)
  const other = createTokens()
  assert.equal(other.isCurrent(second), false) // independent counters

  // colours: own and neutral bubbles are readable
  const colors = await load('utils/chatColors.js')
  assert.ok(contrast(colors.OWN_BUBBLE.text, colors.OWN_BUBBLE.bubble) >= 4.5)
  assert.ok(contrast(colors.NEUTRAL_BUBBLE.text, colors.NEUTRAL_BUBBLE.bubble) >= 4.5)

  console.log('OK: chatAdminCore')
})().catch((e) => {
  console.error('FAIL:', e.message)
  process.exit(1)
})
