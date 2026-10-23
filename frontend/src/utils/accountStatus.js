import { formatLocal } from './formatDate'

// Plain-text status for a 403 login (pending / rejected / revoked), shared by the password
// form and the Google button. Text only - the admin's reason is user-controlled data and is
// never rendered as HTML.
export function statusText(d) {
  const reason = d.reason || 'No reason was given'
  if (d.code === 'ACCOUNT_PENDING') {
    // A brand-new Google sign-up gets its own server wording.
    if (d.message?.startsWith('Your request was sent.')) return d.message
    const when = formatLocal(d.requestedAt)
    return `${when ? `Your request was sent on ${when}. ` : ''}The admin has not decided yet. Log in again later to check. No email is sent.`
  }
  if (d.code === 'ACCOUNT_REJECTED') {
    return `Your request was not approved${d.decidedAt ? ` on ${formatLocal(d.decidedAt)}` : ''}. Reason: ${reason}. Contact your admin.`
  }
  if (d.code === 'ACCOUNT_REVOKED') {
    return `Your access was removed${d.decidedAt ? ` on ${formatLocal(d.decidedAt)}` : ''}. Reason: ${reason}. Contact your admin.`
  }
  return d.message || ''
}
