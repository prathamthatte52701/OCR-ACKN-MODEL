import { useCallback, useEffect, useState } from 'react'
import { nextSidebarHidden, readSidebarHidden, writeSidebarHidden } from '../utils/layoutStorage'

const DESKTOP_QUERY = '(min-width: 768px)'

function matchesDesktop() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(DESKTOP_QUERY).matches
}

// A later phase adds chat panel state here.
export function useLayoutState() {
  const [sidebarHidden, setSidebarHiddenState] = useState(() => readSidebarHidden())
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [isDesktop, setIsDesktop] = useState(matchesDesktop)

  useEffect(() => {
    writeSidebarHidden(sidebarHidden)
  }, [sidebarHidden])

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

  const setSidebarHidden = useCallback((v) => setSidebarHiddenState(Boolean(v)), [])
  const toggleSidebar = useCallback(() => setSidebarHiddenState(nextSidebarHidden), [])
  const openDrawer = useCallback(() => setDrawerOpen(true), [])
  const closeDrawer = useCallback(() => setDrawerOpen(false), [])
  const toggleDrawer = useCallback(() => setDrawerOpen((o) => !o), [])

  return { sidebarHidden, toggleSidebar, setSidebarHidden, drawerOpen, openDrawer, closeDrawer, toggleDrawer, isDesktop }
}
