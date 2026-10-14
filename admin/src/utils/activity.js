// Turns a dashboard activity-feed item into a readable sentence. Unknown actions get a safe
// generic sentence - never raw JSON and never anything that was not whitelisted by the backend.

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`

const SENTENCES = {
  login: (n) => `${n} logged in`,
  signup: (n) => `${n} requested an account`,
  password_change: (n) => `${n} changed a password`,
  user_approved: (n, i) => `${n} approved ${i.targetEmail || 'a user'}`,
  user_rejected: (n, i) => `${n} rejected ${i.targetEmail || 'a user'}`,
  user_updated: (n, i) => `${n} updated ${i.targetEmail || 'a user'}`,
  user_deleted: (n, i) => `${n} deleted ${i.targetEmail || 'a user'}`,
  user_email_changed: (n, i) => `${n} changed the email of ${i.targetEmail || 'a user'}`,
  document_uploaded: (n, i) => `${n} uploaded ${plural(i.count, 'document', 'documents')}`,
  document_processed: (n, i) => `${plural(i.count, 'document was', 'documents were')} processed for ${n}`,
  document_exported: (n, i) => `${n} saved ${plural(i.count, 'document', 'documents')} to Excel`,
  document_corrected: (n, i) => `${n} corrected ${plural(i.count, 'document', 'documents')}`,
  document_edited: (n, i) => `${n} edited ${plural(i.count, 'document', 'documents')}`,
  document_reprocessed: (n, i) => `${n} reprocessed ${plural(i.count, 'document', 'documents')}`,
  document_deleted: (n, i) => `${n} deleted ${plural(i.count, 'document', 'documents')}`,
  document_file_purged: (n, i) => `${n} purged ${plural(i.count, 'original file', 'original files')}`,
  admin_access: (n) => `${n} viewed another user's data`,
  orphaned_file_dismissed: (n) => `${n} dismissed an orphaned file`,
  orphaned_file_retry_succeeded: (n) => `${n} recovered an orphaned file`,
}

export function describeActivity(item) {
  const name = item.user?.username || 'A removed user'
  const fn = SENTENCES[item.action]
  if (fn) return fn(name, item)
  const words = String(item.action || 'did something').replace(/_/g, ' ').trim()
  return `${name}: ${words}`
}

export function relativeTime(iso, now = Date.now()) {
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return ''
  const sec = Math.round((t - now) / 1000)
  const abs = Math.abs(sec)
  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
  if (abs < 45) return 'just now'
  if (abs < 3600) return rtf.format(Math.round(sec / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(sec / 3600), 'hour')
  return rtf.format(Math.round(sec / 86400), 'day')
}
