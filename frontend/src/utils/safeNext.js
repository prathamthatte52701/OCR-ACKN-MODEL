// A post-login redirect target taken from ?next= : same-origin app paths only, never
// "//host" or "/\host" (protocol-relative), never back onto an auth page (redirect loop).
export const AUTH_PATHS = ['/login', '/signup', '/forgot-password', '/set-new-password']

export function safeNext(next, fallback = '/') {
  if (typeof next !== 'string' || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) {
    return fallback
  }
  const path = next.split(/[?#]/)[0]
  return AUTH_PATHS.includes(path) ? fallback : next
}
