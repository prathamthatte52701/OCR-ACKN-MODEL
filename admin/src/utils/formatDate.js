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

export function formatISTDate(dateStr) {
  return formatIST(dateStr, { hour: undefined, minute: undefined, hour12: undefined })
}
