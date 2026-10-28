import { useCallback, useEffect, useRef, useState } from 'react'
import { bumpMutation, bumpRequest, createState, isStale, markFinished, markStarted, recordFailure, recordSuccess, resetBackoff, shouldRun } from '../utils/autoRefreshCore'
import { onServerDownChange } from '../utils/api'
import { ADMIN_TICK_EVENT } from '../utils/events'

// Quiet refresh of a page's data on every shell heartbeat. fetchData() only fetches; applyData(data)
// runs only if nothing local changed and no newer load started since the fetch began. No loading flag
// and no error on failure: the old data stays until the next beat.
// markChanged() - call at the START of every local write.
// noteLoad()     - call at the start of every user-triggered load (first load, filter, page, retry).
export function useAutoRefresh({ fetchData, applyData, busy = false, modalOpen = false, minIntervalMs = 0, enabled = true }) {
  const [state] = useState(createState)
  const latest = useRef({ fetchData, applyData, busy, modalOpen, minIntervalMs })

  useEffect(() => {
    latest.current = { fetchData, applyData, busy, modalOpen, minIntervalMs }
  })

  useEffect(() => {
    if (!enabled) return undefined
    let mounted = true
    async function onTick() {
      const now = Date.now()
      const cur = latest.current
      const gate = { visible: document.visibilityState === 'visible', now, busy: cur.busy, modalOpen: cur.modalOpen, minIntervalMs: cur.minIntervalMs }
      if (!shouldRun(state, gate)) return
      const started = markStarted(state, now)
      try {
        const data = await cur.fetchData()
        recordSuccess(state)
        if (mounted && !isStale(state, started.mutation, started.requestId)) latest.current.applyData(data)
      } catch (err) {
        recordFailure(state, err?.response?.status)
      } finally {
        markFinished(state)
      }
    }
    window.addEventListener(ADMIN_TICK_EVENT, onTick)
    const stopWatching = onServerDownChange((down) => { if (!down) resetBackoff(state) })
    return () => {
      mounted = false
      stopWatching()
      window.removeEventListener(ADMIN_TICK_EVENT, onTick)
    }
  }, [enabled, state])

  const markChanged = useCallback(() => bumpMutation(state), [state])
  const noteLoad = useCallback(() => bumpRequest(state), [state])
  return { markChanged, noteLoad }
}
