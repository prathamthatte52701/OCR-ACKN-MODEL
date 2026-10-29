import { useCallback, useEffect, useRef, useState } from 'react'
import { CHAT_OPEN_KEY, readSidebarHidden, toggleAndPersist, writeSidebarHidden } from '../utils/layoutStorage'

const DESKTOP_QUERY = '(min-width: 1024px)'
const DOCK_QUERY = '(min-width: 1280px)' // chat docks beside the content from here, overlays below

function matches(query) {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(query).matches
}

export function useLayoutState() {
  const [sidebarHidden, setSidebarHiddenState] = useState(() => readSidebarHidden())
  const hiddenRef = useRef(sidebarHidden) // latest value; persisted inside the handlers, not in an effect
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [isDesktop, setIsDesktop] = useState(() => matches(DESKTOP_QUERY))
  const [chatDocked, setChatDocked] = useState(() => matches(DOCK_QUERY))
  // The stored chat flag only applies when docked; an overlay always starts closed.
  const [chatOpen, setChatOpenState] = useState(() => matches(DOCK_QUERY) && readSidebarHidden(CHAT_OPEN_KEY))
  const chatRef = useRef(chatOpen)

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

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined
    const mql = window.matchMedia(DOCK_QUERY)
    function onChange(e) {
      const open = e.matches && readSidebarHidden(CHAT_OPEN_KEY)
      chatRef.current = open
      setChatDocked(e.matches)
      setChatOpenState(open)
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

  // One overlay at a time: an overlaid chat and the sidebar drawer close each other.
  const setChatOpen = useCallback(
    (next) => {
      chatRef.current = next
      if (chatDocked) writeSidebarHidden(next, CHAT_OPEN_KEY)
      else if (next) setDrawerOpen(false)
      setChatOpenState(next)
    },
    [chatDocked],
  )
  const toggleChat = useCallback(() => setChatOpen(!chatRef.current), [setChatOpen])
  const closeChat = useCallback(() => setChatOpen(false), [setChatOpen])

  const dismissOverlayChat = useCallback(() => {
    if (chatDocked) return
    chatRef.current = false
    setChatOpenState(false)
  }, [chatDocked])
  const openDrawer = useCallback(() => {
    dismissOverlayChat()
    setDrawerOpen(true)
  }, [dismissOverlayChat])
  const closeDrawer = useCallback(() => setDrawerOpen(false), [])
  const toggleDrawer = useCallback(() => {
    dismissOverlayChat()
    setDrawerOpen((o) => !o)
  }, [dismissOverlayChat])

  return {
    sidebarHidden, toggleSidebar, setSidebarHidden,
    drawerOpen, openDrawer, closeDrawer, toggleDrawer, isDesktop,
    chatOpen, chatDocked, toggleChat, closeChat,
  }
}
