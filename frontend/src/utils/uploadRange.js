// "UPLOAD BY DATE" chips are calendar based in the USER's local timezone. The browser works
// out the start instant and sends it as an ISO (UTC) string; the URL only ever holds the chip
// NAME, so a stale timestamp can never outlive the day it was computed on.
export const UPLOAD_RANGES = [
  { value: 'today', label: 'Today' },
  { value: 'week', label: 'This Week' },
  { value: 'month', label: 'This Month' },
  { value: 'year', label: 'This Year' },
]

// Local 00:00 of today / this Monday / the 1st of this month / 1 Jan. `now` is injectable for tests.
export function uploadStart(range, now = new Date()) {
  const y = now.getFullYear()
  const m = now.getMonth()
  const d = now.getDate()
  if (range === 'today') return new Date(y, m, d)
  if (range === 'week') return new Date(y, m, d - ((now.getDay() + 6) % 7)) // Monday = start
  if (range === 'month') return new Date(y, m, 1)
  if (range === 'year') return new Date(y, 0, 1)
  return null
}

export function uploadedFromParam(range, now = new Date()) {
  const start = uploadStart(range, now)
  return start ? start.toISOString() : undefined
}
