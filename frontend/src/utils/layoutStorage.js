export const SIDEBAR_HIDDEN_KEY = 'ackn.user.sidebarHidden'

// localStorage can throw on access itself (blocked cookies, private mode), so resolve it lazily.
function resolve(storage) {
  try {
    return storage ?? globalThis.localStorage ?? null
  } catch {
    return null
  }
}

export function readSidebarHidden(key = SIDEBAR_HIDDEN_KEY, storage) {
  try {
    const s = resolve(storage)
    return s ? s.getItem(key) === 'true' : false
  } catch {
    return false
  }
}

export function writeSidebarHidden(hidden, key = SIDEBAR_HIDDEN_KEY, storage) {
  try {
    const s = resolve(storage)
    if (!s) return false
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
