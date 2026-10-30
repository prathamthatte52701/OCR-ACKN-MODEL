// Pure admin-chat rules: no React, no browser globals at import time.

export const BADGE_CAP = 99
export const SEARCH_FROM = 8 // the user list gets a search box when it has more users than this

export const CLEAR_RANGES = [
  { id: '24h', label: 'Older than 24 hours' },
  { id: '3d', label: 'Older than 3 days' },
  { id: '1w', label: 'Older than 1 week' },
  { id: '1m', label: 'Older than 1 month' },
  { id: '3m', label: 'Older than 3 months' },
  { id: '6m', label: 'Older than 6 months' },
  { id: '1y', label: 'Older than 1 year' },
  { id: 'all', label: 'All messages' },
]

export function unreadTotal(byUser) {
  return (byUser ?? []).reduce((sum, row) => sum + (row.count || 0), 0)
}

// The threads list and the unread counts refresh at different moments. When the counts are loaded
// they are the fresher source, so a user missing from them has no unread messages.
export function overlayUnread(threads, byUser) {
  if (!byUser) return threads
  const counts = new Map(byUser.map((row) => [row.userId, row.count]))
  return threads.map((t) => ({ ...t, unreadCount: counts.get(t.userId) ?? 0 }))
}

// The remembered user if they are still in the list, else the first with unread messages, else the first.
export function pickSelected(threads, storedId) {
  if (!threads.length) return null
  if (storedId && threads.some((t) => t.userId === storedId)) return storedId
  return (threads.find((t) => t.unreadCount > 0) ?? threads[0]).userId
}

// Messages from the user to THIS admin that are still unread (a message addressed to the other admin
// is that admin's to read, so it never triggers a mark-read here).
export function unreadForAdmin(messages, adminId) {
  return messages.filter((m) => m.fromRole === 'user' && m.toAdminId === adminId && !m.readAt)
}

export function badgeText(n) {
  if (!(n > 0)) return ''
  return n > BADGE_CAP ? `${BADGE_CAP}+` : String(n)
}

// " and 2 files" when chat files go with the messages, nothing otherwise.
export function filesPart(files) {
  return files > 0 ? ` and ${files} ${files === 1 ? 'file' : 'files'}` : ''
}

export function clearSummary(range, count, files = 0) {
  if (count === 0) return 'No messages match this range.'
  const label = CLEAR_RANGES.find((r) => r.id === range)?.label ?? ''
  const scope = label ? ` (${label.charAt(0).toLowerCase()}${label.slice(1)})` : ''
  return `${count} ${count === 1 ? 'message' : 'messages'}${filesPart(files)} will be deleted${scope}`
}

// Exact word, exact case, no trimming: "delete" and "DELETE " do not count.
export function isTyped(text) {
  return text === 'DELETE'
}

// Plain-words error for "delete ALL chat messages". The server's own sentence is kept for the cases
// it words well (wrong password, Google-only account); the rate limit gets a fixed sentence.
export function describeGlobalClearError(err) {
  if (!err?.response) return 'Could not reach the server. Nothing was deleted.'
  if (err.response.status === 429) return 'Too many tries. Try again in an hour.'
  return err.userMessage || 'Could not delete the messages. Nothing was deleted.'
}

export function filterThreads(threads, query) {
  const q = query.trim().toLowerCase()
  return q ? threads.filter((t) => t.name.toLowerCase().includes(q)) : threads
}

// Hands out a token per request; only the newest token is still current, so a slow answer to an
// older request can be recognised and dropped.
export function createTokens() {
  let latest = 0
  return {
    next: () => {
      latest += 1
      return latest
    },
    isCurrent: (token) => token === latest,
  }
}
