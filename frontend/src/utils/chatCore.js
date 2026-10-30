// Pure chat logic: no React, no browser globals at import time.

export const MAX_CHARS = 1000

function byTimeThenId(a, b) {
  const diff = Date.parse(a.createdAt) - Date.parse(b.createdAt)
  if (diff !== 0) return diff
  if (a.id === b.id) return 0
  return a.id < b.id ? -1 : 1
}

// Dedupe by id (the incoming copy wins, so an edit or read receipt replaces the old one), then
// order by createdAt and id.
export function mergeMessages(prev = [], incoming = []) {
  const byId = new Map()
  for (const m of prev) byId.set(m.id, m)
  for (const m of incoming) byId.set(m.id, m)
  return [...byId.values()].sort(byTimeThenId)
}

export function newestId(messages) {
  return messages.length ? messages[messages.length - 1].id : null
}

export function incomingUnreadIds(messages) {
  return messages.filter((m) => m.fromRole === 'admin' && !m.readAt).map((m) => m.id)
}

// The server counts Unicode code points (Python len), not UTF-16 units.
export function countChars(text) {
  return [...text].length
}

// Cuts text to the limit without splitting a character (a plain slice could cut an emoji in half).
export function clampText(text, max = MAX_CHARS) {
  const chars = [...text]
  return chars.length > max ? chars.slice(0, max).join('') : text
}

// Enter submits; Shift+Enter is a new line; Enter that confirms an IME composition is not a submit.
export function isSubmitKey(e) {
  return e.key === 'Enter' && !e.shiftKey && !e.nativeEvent?.isComposing
}

// Milliseconds from `now` until the soonest still-open edit window among the viewer's own messages
// closes (on the server clock), or null when none is open.
export function nextEditExpiry(messages, serverOffsetMs, now) {
  const serverNow = now + serverOffsetMs
  let soonest = null
  for (const m of messages) {
    if (!m.mine || !m.editableUntil) continue
    const closes = Date.parse(m.editableUntil)
    if (closes > serverNow && (soonest === null || closes < soonest)) soonest = closes
  }
  return soonest === null ? null : soonest - serverNow
}

// Milliseconds to add to the browser clock to get the server clock.
export function serverOffset(serverTime, now) {
  return Date.parse(serverTime) - now
}

export function canEditNow(editableUntil, serverOffsetMs, now) {
  if (!editableUntil) return false
  return Date.parse(editableUntil) > now + serverOffsetMs
}

// Folds freshly fetched messages into the cached thread as it is NOW (`latest`), not as it was when
// the request started: a send or "Load older" that finished in between must not be overwritten.
export function threadFromPage({ latest, hadPrev, fetched, page, now }) {
  return {
    messages: mergeMessages(latest?.messages, fetched),
    nextSince: page.nextSince,
    hasOlder: hadPrev && latest ? latest.hasOlder : page.hasMore,
    offset: serverOffset(page.serverTime, now),
  }
}

// True when the server holds fewer messages than we have cached, i.e. an admin cleared the chat.
export function threadWasCleared(messages, threadCount) {
  return threadCount < messages.length
}

// ---- file attachments (the server re-checks everything; this is only for fast feedback) ----

export const IMAGE_MAX_BYTES = 2 * 1024 * 1024
export const PDF_MAX_BYTES = 3 * 1024 * 1024
export const ALLOWED_TYPES = {
  'image/jpeg': 'image',
  'image/png': 'image',
  'image/webp': 'image',
  'application/pdf': 'pdf',
}
const EXTENSIONS = { jpg: 'image', jpeg: 'image', png: 'image', webp: 'image', pdf: 'pdf' }

// 'image' | 'pdf' | null. A browser hint only: the server decides from the file's bytes.
export function fileKind(file) {
  if (!file) return null
  if (file.type) return ALLOWED_TYPES[file.type] ?? null
  const ext = String(file.name || '').split('.').pop().toLowerCase()
  return EXTENSIONS[ext] ?? null
}

// Plain error text, or null when the file looks fine.
export function validateFile(file) {
  if (!file) return null
  const kind = fileKind(file)
  if (!kind) return 'This file type is not allowed. Use JPG, PNG, WebP or PDF.'
  if (!file.size) return 'This file could not be read.'
  if (kind === 'image' && file.size > IMAGE_MAX_BYTES) return 'Images can be up to 2 MB.'
  if (kind === 'pdf' && file.size > PDF_MAX_BYTES) return 'PDFs can be up to 3 MB.'
  return null
}

export function formatBytes(n) {
  if (!(n >= 0)) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export function attachmentLabel(att) {
  if (!att) return ''
  return att.expired ? 'File expired' : `${att.name} (${formatBytes(att.size)})`
}

// A message needs text or a file; the text keeps the 1000 code point rule either way.
export function canSend({ text = '', file = null }) {
  if (countChars(text) > MAX_CHARS) return false
  return text.trim() !== '' || Boolean(file)
}

export function fileSendErrorText(err) {
  const status = err?.response?.status
  if (!status) return couldNot('send')
  if (status === 429) return 'Too many files. Try again in a while.'
  return err.userMessage || couldNot('send')
}

const couldNot = (what) => `Could not ${what}. Your text is still here.`

export function sendErrorText(err) {
  if (!err?.response) return couldNot('send')
  if (err.response.status === 429) return 'Too many messages. Try again in a while.'
  return err.userMessage || couldNot('send')
}

export function editErrorText(err) {
  if (!err?.response) return couldNot('save')
  return err.userMessage || couldNot('save')
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`
}

export function buildSummaryText({ processedToday, processedTodayByType }) {
  const total = processedToday || 0
  const head = `Today I processed ${plural(total, 'document', 'documents')}`
  if (total === 0) return `${head}.`
  const tax = processedTodayByType?.['Tax Invoice'] || 0
  const challan = processedTodayByType?.['Delivery Challan'] || 0
  const parts = []
  if (tax > 0) parts.push(plural(tax, 'Tax Invoice', 'Tax Invoices'))
  if (challan > 0) parts.push(plural(challan, 'Delivery Challan', 'Delivery Challans'))
  const other = total - tax - challan
  if (other > 0) parts.push(`${other} other`)
  return `${head}: ${parts.join(', ')}.`
}
