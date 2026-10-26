import { useCallback, useRef, useState } from 'react'
import { readSidebarHidden, toggleAndPersist, writeSidebarHidden } from '../utils/layoutStorage'

// Shell layout state. A later phase adds the chat panel state here.
// Persistence happens inside the handlers (ref holds the latest value), not in an effect.
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
  return { sidebarHidden, toggleSidebar, setSidebarHidden }
}
