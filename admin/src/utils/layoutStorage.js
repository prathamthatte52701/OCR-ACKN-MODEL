// Persists the "sidebar hidden" preference. Plain module: no React, no browser globals at import time.
export const SIDEBAR_HIDDEN_KEY = 'ackn.admin.sidebarHidden'
export const CHAT_OPEN_KEY = 'ackn.admin.chatOpen'
const CHAT_USER_PREFIX = 'ackn.admin.chatUser.'

// The chat user an admin last had open, remembered per admin id.
export const chatUserKey = (adminId) => `${CHAT_USER_PREFIX}${adminId}`

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

// Flips ref.current and persists it synchronously (no effect/render needed). Returns the new value.
export function toggleAndPersist(ref, key = SIDEBAR_HIDDEN_KEY, storage) {
  const next = nextSidebarHidden(ref.current)
  ref.current = next
  writeSidebarHidden(next, key, storage)
  return next
}

export function readStored(key, storage) {
  try {
    return (storage ?? globalThis.localStorage).getItem(key)
  } catch {
    return null
  }
}

export function writeStored(key, value, storage) {
  try {
    ;(storage ?? globalThis.localStorage).setItem(key, value)
    return true
  } catch {
    return false
  }
}

export function removeStored(key, storage) {
  try {
    ;(storage ?? globalThis.localStorage).removeItem(key)
  } catch {
    // nothing to remove
  }
}

// Logout: no remembered chat user (and no open-panel flag) stays behind for the next admin on this browser.
export function removeChatUserKeys(storage) {
  try {
    const s = storage ?? globalThis.localStorage
    const stale = []
    for (let i = 0; i < s.length; i += 1) {
      const key = s.key(i)
      if (key === CHAT_OPEN_KEY || key?.startsWith(CHAT_USER_PREFIX)) stale.push(key)
    }
    stale.forEach((key) => s.removeItem(key))
    return stale.length
  } catch {
    return 0
  }
}
