import { useCallback, useEffect, useState } from 'react'
import { nextSidebarHidden, readSidebarHidden, writeSidebarHidden } from '../utils/layoutStorage'

// Shell layout state. A later phase adds the chat panel state here.
export function useLayoutState() {
  const [sidebarHidden, setSidebarHidden] = useState(() => readSidebarHidden())
  useEffect(() => { writeSidebarHidden(sidebarHidden) }, [sidebarHidden])
  const toggleSidebar = useCallback(() => setSidebarHidden(nextSidebarHidden), [])
  return { sidebarHidden, toggleSidebar, setSidebarHidden }
}
