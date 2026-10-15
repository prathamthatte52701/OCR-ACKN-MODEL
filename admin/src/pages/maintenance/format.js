// Small formatting helpers for the Maintenance page (pure functions, no UI).

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

// 0 -> "0 B", 1536 -> "1.5 KB", 123456789 -> "118 MB". At most 3 significant digits so it fits the donut centre.
export function formatBytes(bytes) {
  let n = Number(bytes)
  if (!Number.isFinite(n) || n <= 0) return '0 B'
  let i = 0
  while (n >= 1024 && i < UNITS.length - 1) {
    n /= 1024
    i += 1
  }
  if (i > 0 && n >= 1023.5 && i < UNITS.length - 1) {
    n /= 1024
    i += 1
  }
  const text = i === 0 || n >= 100 ? String(Math.round(n)) : n.toFixed(1).replace(/\.0$/, '')
  return `${text} ${UNITS[i]}`
}

// Process uptime: "3d 4h", "5h 12m", "7m", "20s".
export function formatUptime(seconds) {
  const s = Math.floor(Number(seconds))
  if (!Number.isFinite(s) || s < 0) return '-'
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m`
  return `${s}s`
}

export function localDateTime(iso) {
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return ''
  return t.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`

// Maintenance audit events -> readable sentence + category badge. Unknown actions get a safe generic line.
const EVENTS = {
  admin_nuke_global_range_data: { text: (n) => `${n} ran a global delete by age`, label: 'Global delete', tone: 'red' },
  admin_nuke_global_months_data: { text: (n) => `${n} ran a global delete by month`, label: 'Global delete', tone: 'red' },
  admin_nuke_user_range_data: { text: (n) => `${n} ran a delete by age on one user`, label: 'User delete', tone: 'red' },
  admin_nuke_user_months_data: { text: (n) => `${n} ran a delete by month on one user`, label: 'User delete', tone: 'red' },
  document_file_purged: { text: (n) => `${n} purged a stored file`, label: 'File purge', tone: 'amber' },
  orphaned_file_dismissed: { text: (n) => `${n} dismissed an orphaned file`, label: 'Orphaned file', tone: 'blue' },
  orphaned_file_retry_succeeded: { text: (n) => `${n} recovered an orphaned file`, label: 'Orphaned file', tone: 'teal' },
  user_deleted: { text: (n) => `${n} deleted a user`, label: 'User', tone: 'violet' },
}

export function describeMaintenance(item) {
  const name = item.user?.username || 'A removed user'
  const ev = EVENTS[item.action]
  if (ev) return { text: ev.text(name), label: ev.label, tone: ev.tone }
  return { text: `${name}: ${String(item.action || 'did something').replace(/_/g, ' ')}`, label: 'Maintenance', tone: 'neutral' }
}
