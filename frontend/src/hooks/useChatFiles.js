import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react'

const MAX_PARALLEL = 4

// Blob cache for chat attachments, alive only while `scope` stays the same (panel open, same
// user/thread). Changing or clearing the scope revokes every object URL, empties the queue and
// makes any in-flight answer a no-op (its blob is dropped before a URL is ever made).
// entry: { state: 'loading' | 'ready' | 'expired' | 'missing', url?: string }
export function useChatFiles(scope, fetchFile) {
  const cache = useRef(new Map())
  const queue = useRef([])
  const active = useRef(0)
  const epoch = useRef(0)
  const [, bump] = useReducer((n) => n + 1, 0)

  useEffect(() => {
    const entries = cache.current
    return () => {
      epoch.current += 1
      for (const e of entries.values()) if (e.url) URL.revokeObjectURL(e.url)
      entries.clear()
      queue.current = []
      active.current = 0
    }
  }, [scope])

  const pump = useCallback(function run() {
    while (active.current < MAX_PARALLEL && queue.current.length) {
      const id = queue.current.shift()
      const mine = epoch.current
      active.current += 1
      fetchFile(id)
        .then((blob) => {
          if (epoch.current === mine) cache.current.set(id, { state: 'ready', url: URL.createObjectURL(blob) })
        })
        .catch((err) => {
          if (epoch.current === mine) {
            const status = err?.response?.status
            // only 404/410 are final; a 429 or network blip is dropped so a later view retries
            if (status === 410) cache.current.set(id, { state: 'expired' })
            else if (status === 404) cache.current.set(id, { state: 'missing' })
            else cache.current.delete(id)
          }
        })
        .finally(() => {
          if (epoch.current !== mine) return
          active.current -= 1
          bump()
          run()
        })
    }
  }, [fetchFile])

  const request = useCallback(
    (id) => {
      if (scope == null || cache.current.has(id)) return
      cache.current.set(id, { state: 'loading' })
      queue.current.push(id)
      pump()
    },
    [scope, pump],
  )

  const get = useCallback((id) => cache.current.get(id), [])
  // For a message that was deleted: drop its blob and URL right away.
  const forget = useCallback((id) => {
    const e = cache.current.get(id)
    if (e?.url) URL.revokeObjectURL(e.url)
    cache.current.delete(id)
    bump()
  }, [])

  return useMemo(() => ({ request, get, forget }), [request, get, forget])
}
