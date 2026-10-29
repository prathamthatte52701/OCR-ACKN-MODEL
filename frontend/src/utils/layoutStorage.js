export const SIDEBAR_HIDDEN_KEY = 'ackn.user.sidebarHidden'
export const CHAT_OPEN_KEY = 'ackn.user.chatOpen'

export const chatAdminKey = (userId) => `ackn.user.chatAdmin.${userId}`

// localStorage can throw on access itself (blocked cookies, private mode), so resolve it lazily.
function resolve(storage) {
  try {
    return storage ?? globalThis.localStorage ?? null
  } catch {
    return null
  }
}

export function readStored(key, storage) {
  try {
    const s = resolve(storage)
    return s ? s.getItem(key) : null
  } catch {
    return null
  }
}

export function writeStored(key, value, storage) {
  try {
    const s = resolve(storage)
    if (!s) return false
    s.setItem(key, value)
    return true
  } catch {
    return false
  }
}

// The boolean helpers below serve both flags (sidebar hidden, chat open); only the key differs.
export function readSidebarHidden(key = SIDEBAR_HIDDEN_KEY, storage) {
  return readStored(key, storage) === 'true'
}

export function writeSidebarHidden(hidden, key = SIDEBAR_HIDDEN_KEY, storage) {
  return writeStored(key, hidden ? 'true' : 'false', storage)
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
