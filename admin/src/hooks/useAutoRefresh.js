import { useCallback, useEffect, useRef } from 'react'
import { ADMIN_TICK_EVENT } from '../utils/events'
import {
  bumpVersion,
  createAutoRefreshState,
  endRefresh,
  isStaleResponse,
  setBusy,
  setModalOpen,
  shouldRefreshOnTick,
  shouldRefreshOnVisibleFocus,
  startRefresh,
} from '../utils/autoRefreshCore'

export function useAutoRefresh({
  load,
  getBusy = () => false,
  getModalOpen = () => false,
  enabled = true,
  intervalMs = 15000,
  dashboard = false,
}) {
  const stateRef = useRef(createAutoRefreshState())
  const loadRef = useRef(load)
  loadRef.current = load

  const refreshQuietly = useCallback(async () => {
    if (!enabled) return
    const state = stateRef.current
    const visible = typeof document !== 'undefined' ? document.visibilityState === 'visible' : true
    if (!shouldRefreshOnTick(state, visible)) return
    if (!startRefresh(state)) return
    const startedVersion = state.version
    try {
      const res = await loadRef.current({ quiet: true })
      if (isStaleResponse(state, startedVersion)) return
      return res
    } finally {
      endRefresh(state)
    }
  }, [enabled])

  const onVisibleFocus = useCallback(() => {
    if (!enabled) return
    const state = stateRef.current
    const visible = typeof document !== 'undefined' ? document.visibilityState === 'visible' : true
    if (!visible) return
    if (!shouldRefreshOnVisibleFocus(state)) return
    refreshQuietly()
  }, [enabled, refreshQuietly])

  useEffect(() => {
    const state = stateRef.current
    setBusy(state, getBusy())
    setModalOpen(state, getModalOpen())
  })

  useEffect(() => {
    if (!enabled) return
    const state = stateRef.current
    const tick = () => {
      setBusy(state, getBusy())
      setModalOpen(state, getModalOpen())
      refreshQuietly()
    }
    const interval = setInterval(tick, dashboard ? 60000 : intervalMs)
    window.addEventListener(ADMIN_TICK_EVENT, tick)
    window.addEventListener('focus', onVisibleFocus)
    document.addEventListener('visibilitychange', onVisibleFocus)
    return () => {
      clearInterval(interval)
      window.removeEventListener(ADMIN_TICK_EVENT, tick)
      window.removeEventListener('focus', onVisibleFocus)
      document.removeEventListener('visibilitychange', onVisibleFocus)
    }
  }, [enabled, intervalMs, dashboard, refreshQuietly, onVisibleFocus, getBusy, getModalOpen])

  const bumpLocalChange = useCallback(() => {
    bumpVersion(stateRef.current)
  }, [])

  return { bumpLocalChange, refreshQuietly }
}

export default useAutoRefresh
