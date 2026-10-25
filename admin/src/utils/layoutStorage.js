// Persists the "sidebar hidden" preference. Plain module: no React, no browser globals at import time.
export const SIDEBAR_HIDDEN_KEY = 'ackn.admin.sidebarHidden'

// Accessing localStorage itself can throw (blocked site data), so it is resolved lazily inside try/catch.
export function readSidebarHidden(key = SIDEBAR_HIDDEN_KEY, storage) {
  try {
    const s = storage ?? globalThis.localStorage
    return s.getItem(key) === 'true'
  } catch {
    return false
  }
}

export function writeSidebarHidden(hidden, key = SIDEBAR_HIDDEN_KEY, storage) {
  try {
    const s = storage ?? globalThis.localStorage
    s.setItem(key, hidden ? 'true' : 'false')
    return true
  } catch {
    return false
  }
}

export function nextSidebarHidden(current) {
  return !current
}
