// Plain Node check (no runner): node frontend/tests/test_chat_core.cjs
const assert = require('node:assert/strict')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

const msg = (id, createdAt, extra = {}) => ({ id, createdAt, fromRole: 'user', readAt: null, ...extra })

;(async () => {
  assert.equal(typeof window, 'undefined')
  assert.equal(typeof document, 'undefined')
  const core = await import(pathToFileURL(path.join(__dirname, '..', 'src', 'utils', 'chatCore.js')).href)
  const { mergeMessages, newestId, incomingUnreadIds, countChars, canEditNow, serverOffset, buildSummaryText } = core

  // mergeMessages
  assert.deepEqual(mergeMessages([], []), [])
  assert.deepEqual(mergeMessages(undefined, undefined), [])
  const a = msg('a', '2026-10-01T10:00:00Z')
  const b = msg('b', '2026-10-01T10:01:00Z')
  assert.deepEqual(mergeMessages([], [b, a]).map((m) => m.id), ['a', 'b'])
  assert.deepEqual(mergeMessages([a, b], []), [a, b])
  assert.deepEqual(mergeMessages([a, b], [a, b]).map((m) => m.id), ['a', 'b']) // dedupe
  const editedB = { ...b, text: 'new', editedAt: '2026-10-01T10:02:00Z' }
  const merged = mergeMessages([a, b], [editedB])
  assert.equal(merged.length, 2)
  assert.equal(merged[1].text, 'new') // the edit replaces the old copy
  const c = msg('c', '2026-10-01T10:00:00Z')
  assert.deepEqual(mergeMessages([c], [a]).map((m) => m.id), ['a', 'c']) // tie -> by id
  assert.deepEqual(mergeMessages([a], [c]).map((m) => m.id), ['a', 'c']) // same either way
  const prev = [a, b]
  mergeMessages(prev, [editedB])
  assert.deepEqual(prev, [a, b]) // inputs are not mutated
  // older page prepended
  const old = msg('0', '2026-09-30T09:00:00Z')
  assert.deepEqual(mergeMessages([a, b], [old]).map((m) => m.id), ['0', 'a', 'b'])
  // different ISO spellings of the same instant still order by time
  assert.deepEqual(
    mergeMessages([msg('x', '2026-10-01T10:00:00.500000Z')], [msg('y', '2026-10-01T10:00:00Z')]).map((m) => m.id),
    ['y', 'x'],
  )

  // newestId
  assert.equal(newestId([]), null)
  assert.equal(newestId([a, b]), 'b')

  // incomingUnreadIds
  const adminUnread = msg('1', '2026-10-01T10:00:00Z', { fromRole: 'admin' })
  const adminRead = msg('2', '2026-10-01T10:01:00Z', { fromRole: 'admin', readAt: '2026-10-01T10:05:00Z' })
  const mine = msg('3', '2026-10-01T10:02:00Z')
  assert.deepEqual(incomingUnreadIds([adminUnread, adminRead, mine]), ['1'])
  assert.deepEqual(incomingUnreadIds([]), [])
  assert.deepEqual(incomingUnreadIds([adminRead, mine]), [])

  // countChars: code points, like Python len
  assert.equal(countChars(''), 0)
  assert.equal(countChars('hello'), 5)
  assert.equal(countChars('😀'), 1)
  assert.equal('😀'.length, 2)
  assert.equal(countChars('a😀b'), 3)
  assert.equal(countChars('👨‍👩‍👧'), 5) // ZWJ sequence = 3 emoji + 2 joiners, as Python counts it
  assert.equal(countChars('é'), 1)
  assert.equal(countChars('x'.repeat(1000)), 1000)
  assert.equal(countChars('x'.repeat(1001)), 1001)
  assert.equal(countChars('😀'.repeat(1000)), 1000)
  assert.equal(countChars('😀'.repeat(1001)), 1001)
  assert.equal(core.MAX_CHARS, 1000)

  // clampText: the hard limit counts code points and never splits one
  const { clampText, isSubmitKey } = core
  assert.equal(clampText(''), '')
  assert.equal(clampText('abc'), 'abc')
  assert.equal(clampText('x'.repeat(1000)).length, 1000)
  assert.equal(clampText('x'.repeat(1001)).length, 1000)
  assert.equal(clampText('x'.repeat(5000)).length, 1000) // pasted 5000 characters
  assert.equal(countChars(clampText('😀'.repeat(1001))), 1000)
  assert.equal(clampText('😀'.repeat(1001)), '😀'.repeat(1000)) // no half emoji
  assert.equal(clampText('😀'.repeat(600)), '😀'.repeat(600)) // 600 emoji (1200 UTF-16 units) is allowed
  assert.equal(clampText('abcdef', 3), 'abc')

  // isSubmitKey
  assert.equal(isSubmitKey({ key: 'Enter', shiftKey: false, nativeEvent: {} }), true)
  assert.equal(isSubmitKey({ key: 'Enter', shiftKey: false }), true)
  assert.equal(isSubmitKey({ key: 'Enter', shiftKey: true, nativeEvent: {} }), false)
  assert.equal(isSubmitKey({ key: 'Enter', shiftKey: false, nativeEvent: { isComposing: true } }), false)
  assert.equal(isSubmitKey({ key: 'a', shiftKey: false, nativeEvent: {} }), false)

  // canEditNow / serverOffset with a skewed browser clock
  const now = Date.parse('2026-10-01T12:00:00Z')
  const until = '2026-10-01T12:05:00Z' // server says 5 minutes left
  assert.equal(canEditNow(until, 0, now), true)
  assert.equal(canEditNow(until, 0, now + 6 * 60_000), false)
  assert.equal(canEditNow(null, 0, now), false)
  assert.equal(canEditNow(undefined, 0, now), false)
  // browser clock 10 min BEHIND the server: server time is 12:10 when the browser shows 12:00
  const behind = serverOffset('2026-10-01T12:10:00Z', now)
  assert.equal(behind, 10 * 60_000)
  assert.equal(canEditNow(until, behind, now), false) // window already over on the server
  // browser clock 10 min AHEAD: browser shows 12:00 while the server is at 11:50
  const ahead = serverOffset('2026-10-01T11:50:00Z', now)
  assert.equal(ahead, -10 * 60_000)
  assert.equal(canEditNow(until, ahead, now), true) // still 15 min left on the server
  assert.equal(canEditNow(until, ahead, now + 14 * 60_000), true)
  assert.equal(canEditNow(until, ahead, now + 16 * 60_000), false)
  // exact edge: not editable at the instant it ends
  assert.equal(canEditNow(until, 0, Date.parse(until)), false)
  assert.equal(canEditNow(until, 0, Date.parse(until) - 1), true)

  // nextEditExpiry: a stale clock must not keep Edit alive
  const { nextEditExpiry } = core
  const T0 = Date.parse('2026-10-01T12:00:00Z')
  const own = (id, until) => ({ id, mine: true, editableUntil: until })
  const theirs = { id: 't', mine: false, editableUntil: '2026-10-01T12:30:00Z' }
  assert.equal(nextEditExpiry([], 0, T0), null)
  assert.equal(nextEditExpiry([theirs], 0, T0), null) // other people's messages never count
  assert.equal(nextEditExpiry([{ id: 'x', mine: true, editableUntil: null }], 0, T0), null)
  assert.equal(nextEditExpiry([own('a', '2026-10-01T12:05:00Z')], 0, T0), 5 * 60_000)
  assert.equal(nextEditExpiry([own('a', '2026-10-01T12:05:00Z'), own('b', '2026-10-01T12:02:00Z')], 0, T0), 2 * 60_000) // soonest wins
  assert.equal(nextEditExpiry([own('a', '2026-10-01T11:59:00Z')], 0, T0), null) // already closed
  assert.equal(nextEditExpiry([own('a', '2026-10-01T12:00:00Z')], 0, T0), null) // closes exactly now
  // 16 minutes later the same message is closed: re-reading the clock on open/poll hides Edit
  const sent = own('a', '2026-10-01T12:15:00Z')
  assert.equal(nextEditExpiry([sent], 0, T0 + 14 * 60_000), 60_000)
  assert.equal(nextEditExpiry([sent], 0, T0 + 16 * 60_000), null)
  assert.equal(canEditNow(sent.editableUntil, 0, T0 + 16 * 60_000), false)
  assert.equal(canEditNow(sent.editableUntil, 0, T0 + 1_000), true) // a stale (early) clock is the bug
  assert.equal(nextEditExpiry([sent], 10 * 60_000, T0), 5 * 60_000) // server 10 min ahead

  // threadFromPage / threadWasCleared
  const { threadFromPage, threadWasCleared } = core
  const page = { nextSince: '2026-10-01T10:09:00Z', hasMore: true, serverTime: '2026-10-01T10:10:00Z' }
  const t0 = Date.parse('2026-10-01T10:10:00Z')
  const first = threadFromPage({ latest: undefined, hadPrev: false, fetched: [b, a], page, now: t0 })
  assert.deepEqual(first.messages.map((m) => m.id), ['a', 'b'])
  assert.equal(first.hasOlder, true) // initial load: from the page
  assert.equal(first.offset, 0)
  assert.equal(first.nextSince, page.nextSince)
  // a poll that started before "Load older" finished keeps the older page and its hasOlder
  const latest = { messages: [old, a], nextSince: 'x', hasOlder: false, offset: 5 }
  const poll = threadFromPage({ latest, hadPrev: true, fetched: [b], page: { ...page, hasMore: false }, now: t0 })
  assert.deepEqual(poll.messages.map((m) => m.id), ['0', 'a', 'b'])
  assert.equal(poll.hasOlder, false)
  // cache cleared mid-flight: fall back to the page
  assert.equal(threadFromPage({ latest: undefined, hadPrev: true, fetched: [], page, now: t0 }).hasOlder, true)
  assert.equal(threadWasCleared([a, b], 1), true)
  assert.equal(threadWasCleared([a, b], 2), false)
  assert.equal(threadWasCleared([a, b], 50), false)
  assert.equal(threadWasCleared([], 0), false)

  // error texts
  const { sendErrorText, editErrorText } = core
  const http = (status, userMessage) => ({ response: { status }, userMessage })
  assert.equal(sendErrorText(http(422, 'Message is too long (maximum 1000 characters).')), 'Message is too long (maximum 1000 characters).')
  assert.equal(sendErrorText(http(429, 'Too many requests. Please try again later.')), 'Too many messages. Try again in a while.')
  assert.equal(sendErrorText({ message: 'Network Error' }), 'Could not send. Your text is still here.')
  assert.equal(sendErrorText(undefined), 'Could not send. Your text is still here.')
  assert.equal(sendErrorText(http(500, undefined)), 'Could not send. Your text is still here.')
  assert.equal(editErrorText(http(403, 'The 15-minute edit time is over.')), 'The 15-minute edit time is over.')
  assert.equal(editErrorText({ message: 'Network Error' }), 'Could not save. Your text is still here.')

  // buildSummaryText
  const T = 'Tax Invoice'
  const D = 'Delivery Challan'
  assert.equal(
    buildSummaryText({ processedToday: 100, processedTodayByType: { [T]: 60, [D]: 40 } }),
    'Today I processed 100 documents: 60 Tax Invoices, 40 Delivery Challans.',
  )
  assert.equal(buildSummaryText({ processedToday: 0, processedTodayByType: { [T]: 0, [D]: 0 } }), 'Today I processed 0 documents.')
  assert.equal(buildSummaryText({}), 'Today I processed 0 documents.')
  assert.equal(
    buildSummaryText({ processedToday: 1, processedTodayByType: { [T]: 1, [D]: 0 } }),
    'Today I processed 1 document: 1 Tax Invoice.',
  )
  assert.equal(
    buildSummaryText({ processedToday: 1, processedTodayByType: { [T]: 0, [D]: 1 } }),
    'Today I processed 1 document: 1 Delivery Challan.',
  )
  assert.equal(
    buildSummaryText({ processedToday: 5, processedTodayByType: { [T]: 0, [D]: 5 } }),
    'Today I processed 5 documents: 5 Delivery Challans.',
  )
  assert.equal(
    buildSummaryText({ processedToday: 10, processedTodayByType: { [T]: 6, [D]: 3 } }),
    'Today I processed 10 documents: 6 Tax Invoices, 3 Delivery Challans, 1 other.',
  )
  assert.equal(
    buildSummaryText({ processedToday: 4, processedTodayByType: { [T]: 0, [D]: 0 } }),
    'Today I processed 4 documents: 4 other.',
  )
  assert.equal(buildSummaryText({ processedToday: 3 }), 'Today I processed 3 documents: 3 other.')

  console.log('OK: chatCore')
})().catch((e) => {
  console.error('FAIL:', e.message)
  process.exit(1)
})
