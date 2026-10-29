// Formats a stored UTC timestamp for display in IST (Asia/Kolkata).
// Storage stays UTC - this only affects what's shown.
export function formatIST(dateStr, opts = {}) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return '-'
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
    ...opts,
  }).format(date)
}

// "Today" boundary computed in IST, not server-local time - e.g. a doc
// processed at 11:30pm UTC is already "tomorrow" in IST.
export function isTodayIST(dateStr) {
  if (!dateStr) return false
  const fmt = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }) // YYYY-MM-DD
  return fmt.format(new Date(dateStr)) === fmt.format(new Date())
}

// Calendar day in IST as YYYY-MM-DD (groups chat messages under date separators).
export function dayKeyIST(dateStr) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date(dateStr))
}

// "14 Oct 2026, 3:42 PM" in the viewer's own timezone (account decision dates).
export function formatLocal(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true,
  }).format(date).replace(/\bam\b/, 'AM').replace(/\bpm\b/, 'PM')
}
