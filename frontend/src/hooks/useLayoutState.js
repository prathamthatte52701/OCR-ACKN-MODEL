import { useCallback, useEffect, useRef, useState } from 'react'
import { readSidebarHidden, toggleAndPersist, writeSidebarHidden } from '../utils/layoutStorage'

const DESKTOP_QUERY = '(min-width: 1024px)'

function matchesDesktop() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(DESKTOP_QUERY).matches
}

// A later phase adds chat panel state here.
export function useLayoutState() {
  const [sidebarHidden, setSidebarHiddenState] = useState(() => readSidebarHidden())
  const hiddenRef = useRef(sidebarHidden) // latest value; persisted inside the handlers, not in an effect
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [isDesktop, setIsDesktop] = useState(matchesDesktop)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined
    const mql = window.matchMedia(DESKTOP_QUERY)
    function onChange(e) {
      setIsDesktop(e.matches)
      if (e.matches) setDrawerOpen(false)
    }
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  const setSidebarHidden = useCallback((v) => {
    const next = Boolean(v)
    hiddenRef.current = next
    writeSidebarHidden(next)
    setSidebarHiddenState(next)
  }, [])
  const toggleSidebar = useCallback(() => setSidebarHiddenState(toggleAndPersist(hiddenRef)), [])
  const openDrawer = useCallback(() => setDrawerOpen(true), [])
  const closeDrawer = useCallback(() => setDrawerOpen(false), [])
  const toggleDrawer = useCallback(() => setDrawerOpen((o) => !o), [])

  return { sidebarHidden, toggleSidebar, setSidebarHidden, drawerOpen, openDrawer, closeDrawer, toggleDrawer, isDesktop }
}
