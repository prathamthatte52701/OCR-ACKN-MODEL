import { useCallback, useState } from 'react'

// The four "Entries per page" choices every paged list offers, and the one it starts with.
export const PAGE_SIZE_OPTIONS = [30, 50, 75, 100]
export const DEFAULT_PAGE_SIZE = 30

const storageKey = (key) => `pageSize:${key}`

// The saved choice for one list, or the default when nothing valid is saved. Storage can be empty,
// blocked or hold a bad value (40, "abc", ""), so every read is guarded.
export function readPageSize(key) {
  try {
    const raw = window.localStorage.getItem(storageKey(key))
    const n = raw === null || raw.trim() === '' ? NaN : Number(raw)
    return PAGE_SIZE_OPTIONS.includes(n) ? n : DEFAULT_PAGE_SIZE
  } catch {
    return DEFAULT_PAGE_SIZE
  }
}

// [pageSize, setPageSize] for one list (key = e.g. 'documents'). The choice is remembered per list.
export function usePageSize(key) {
  const [size, setSize] = useState(() => readPageSize(key))
  const update = useCallback(
    (next) => {
      const n = Number(next)
      if (!PAGE_SIZE_OPTIONS.includes(n)) return
      setSize(n)
      try {
        window.localStorage.setItem(storageKey(key), String(n))
      } catch {
        // storage unavailable: the choice still applies until the page is closed
      }
    },
    [key],
  )
  return [size, update]
}
