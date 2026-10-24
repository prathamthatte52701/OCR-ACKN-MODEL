// /login?notice=<code> carries ONLY a short code; the text lives here. URL text is never
// rendered, so a crafted link cannot put words on the login page.
const NOTICE_TEXT = Object.freeze({
  pending: 'Waiting for admin approval.',
  rejected: 'Your request was not approved. Contact the admin.',
  revoked: 'Your request was not approved. Contact the admin.',
  sent: 'Your request was sent. Sign in again after the admin approves.',
})

const CODE_FROM_DETAIL = Object.freeze({
  ACCOUNT_PENDING: 'pending',
  ACCOUNT_REJECTED: 'rejected',
  ACCOUNT_REVOKED: 'revoked',
})

const has = (obj, key) => typeof key === 'string' && Object.prototype.hasOwnProperty.call(obj, key)

// Exact match only; anything unknown (missing, odd case, '__proto__', ...) gives ''.
export function noticeText(code) {
  return has(NOTICE_TEXT, code) ? NOTICE_TEXT[code] : ''
}

// 403 detail from the server -> notice code, or null when it is not an account-status 403.
// A brand-new Google sign-up is a pending account with its own wording -> 'sent'.
export function codeFromDetail(detail) {
  const code = has(CODE_FROM_DETAIL, detail?.code) ? CODE_FROM_DETAIL[detail.code] : null
  if (code === 'pending' && typeof detail.message === 'string' && detail.message.startsWith('Your request was sent.')) {
    return 'sent'
  }
  return code
}
