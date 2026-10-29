export const SIDEBAR_HIDDEN_KEY = 'ackn.user.sidebarHidden'
export const CHAT_OPEN_KEY = 'ackn.user.chatOpen'

const CHAT_ADMIN_PREFIX = 'ackn.user.chatAdmin.'
export const chatAdminKey = (userId) => `${CHAT_ADMIN_PREFIX}${userId}`

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

// Logout (every path): the next person on this browser starts with no chat panel state and no
// remembered admin choice from the previous user.
export function removeChatKeys(storage) {
  try {
    const s = resolve(storage)
    if (!s) return 0
    const stale = []
    for (let i = 0; i < s.length; i += 1) {
      const key = s.key(i)
      if (key === CHAT_OPEN_KEY || key?.startsWith(CHAT_ADMIN_PREFIX)) stale.push(key)
    }
    stale.forEach((key) => s.removeItem(key))
    return stale.length
  } catch {
    return 0
  }
}
