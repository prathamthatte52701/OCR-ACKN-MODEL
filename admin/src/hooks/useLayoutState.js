import { useCallback, useEffect, useRef, useState } from 'react'
import { CHAT_OPEN_KEY, readSidebarHidden, toggleAndPersist, writeSidebarHidden } from '../utils/layoutStorage'

const DOCK_QUERY = '(min-width: 1280px)' // chat docks beside the content from here, overlays below

function matchesDock() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(DOCK_QUERY).matches
}

// Shell layout state: the sidebar preference and the chat panel.
// Persistence happens inside the handlers (ref holds the latest value), not in an effect.
// The stored chat flag only applies when docked; an overlay always starts closed.
export function useLayoutState() {
  const [sidebarHidden, setState] = useState(() => readSidebarHidden())
  const ref = useRef(sidebarHidden)
  const toggleSidebar = useCallback(() => setState(toggleAndPersist(ref)), [])
  const setSidebarHidden = useCallback((v) => {
    const next = Boolean(v)
    ref.current = next
    writeSidebarHidden(next)
    setState(next)
  }, [])

  const [chatDocked, setChatDocked] = useState(matchesDock)
  const [chatOpen, setChatOpenState] = useState(() => matchesDock() && readSidebarHidden(CHAT_OPEN_KEY))
  const chatRef = useRef(chatOpen)

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

  const setChatOpen = useCallback(
    (next) => {
      chatRef.current = next
      if (chatDocked) writeSidebarHidden(next, CHAT_OPEN_KEY)
      setChatOpenState(next)
    },
    [chatDocked],
  )
  const toggleChat = useCallback(() => setChatOpen(!chatRef.current), [setChatOpen])
  const closeChat = useCallback(() => setChatOpen(false), [setChatOpen])

  return { sidebarHidden, toggleSidebar, setSidebarHidden, chatOpen, chatDocked, toggleChat, closeChat }
}
