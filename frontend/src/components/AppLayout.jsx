import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useCallback, useEffect, useRef } from 'react'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useAuthStore } from '../store/authStore'
import { useLayoutState } from '../hooks/useLayoutState'
import AppSidebar from './AppSidebar'

export default function AppLayout() {
  const { sidebarHidden, toggleSidebar, drawerOpen, closeDrawer, toggleDrawer, isDesktop } = useLayoutState()
  const user = useAuthStore((s) => s.user)
  const clear = useAuthStore((s) => s.clear)
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const toggleRef = useRef(null)
  const panelRef = useRef(null)
  const initials = (user?.username || '??').slice(0, 2).toUpperCase()

  const drawerShown = !isDesktop && drawerOpen
  const sidebarShown = isDesktop ? !sidebarHidden : drawerShown

  function handleLogout() {
    clear()
    navigate('/login', { replace: true })
  }

  function handleToggle() {
    if (isDesktop) toggleSidebar()
    else toggleDrawer()
  }

  // Close the drawer on route change. A link clicked inside the drawer unmounts with it, so give
  // focus back to the toggle instead of letting it fall to <body>.
  // The header is inert while the drawer is open, so focus can only move back to the toggle AFTER
  // the drawer has closed: remember the wish here and act on it when drawerShown turns false.
  const refocusToggle = useRef(false)
  const closeDrawerAndRefocus = useCallback(() => {
    refocusToggle.current = true
    closeDrawer()
  }, [closeDrawer])
  useEffect(() => {
    closeDrawer()
  }, [pathname, closeDrawer])
  useEffect(() => {
    if (!drawerShown && refocusToggle.current) {
      refocusToggle.current = false
      toggleRef.current?.focus()
    }
  }, [drawerShown])

  // Drawer: Escape closes and returns focus to the toggle; lock body scroll; focus the panel.
  useEffect(() => {
    if (!drawerShown) return undefined
    function onKeyDown(e) {
      if (e.key === 'Escape') closeDrawerAndRefocus()
    }
    document.addEventListener('keydown', onKeyDown)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    panelRef.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = prevOverflow
    }
  }, [drawerShown, closeDrawerAndRefocus])

  const toggleLabel = sidebarShown ? 'Hide sidebar' : 'Show sidebar'
  const ToggleIcon = sidebarShown ? PanelLeftClose : PanelLeftOpen

  return (
    <div className="flex min-h-screen flex-col overflow-x-clip bg-[#020817] text-slate-100">
      {/* Header */}
      <header inert={drawerShown} className="sticky top-0 z-50 border-b border-blue-400/10 bg-slate-950/72 shadow-[0_14px_40px_rgba(2,8,23,0.28)] backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1440px] items-center justify-between gap-2 px-4 sm:px-6 lg:px-10">
          <div className="flex min-w-0 items-center gap-3">
            <button
              ref={toggleRef}
              type="button"
              onClick={handleToggle}
              aria-label={toggleLabel}
              title={toggleLabel}
              aria-expanded={sidebarShown}
              aria-controls={sidebarShown ? 'app-sidebar' : undefined}
              className="shrink-0 rounded-lg border border-white/10 bg-white/[0.04] p-2 text-slate-300 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 motion-reduce:transition-none"
            >
              <ToggleIcon className="h-5 w-5" aria-hidden="true" />
            </button>
            <NavLink to="/" className="group flex min-w-0 items-center gap-3 text-white no-underline">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-blue-400/30 bg-blue-500/15 text-[14.7px] font-black text-blue-200 shadow-[0_0_28px_rgba(37,99,235,0.35)] transition-colors group-hover:border-cyan-300/50">
                AI
              </span>
              <span className="hidden min-w-0 leading-tight sm:block">
                <span className="block text-base font-bold tracking-tight">AckIntel AI</span>
                <span className="block truncate text-[10.5px] font-medium uppercase tracking-[0.22em] text-slate-500">Acknowledgement Command Center</span>
              </span>
            </NavLink>
          </div>

          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <NavLink
              to="/profile"
              aria-label="Profile"
              className={({ isActive }) =>
                `flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] py-1 pl-1 pr-1 no-underline transition-colors hover:border-blue-300/30 sm:pr-3 ${isActive ? 'border-blue-300/30' : ''}`
              }
            >
              <span className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-blue-500 to-cyan-400 text-[12.6px] font-bold text-white">{initials}</span>
              <span className="hidden max-w-[10rem] truncate text-[12.6px] font-semibold text-slate-300 sm:inline">{user?.username}</span>
            </NavLink>
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-full border border-white/10 bg-white/[0.035] px-3 py-2 text-[12.6px] font-bold text-slate-300 transition-colors hover:border-rose-300/30 hover:bg-rose-500/10 hover:text-rose-200 sm:px-4"
            >
              Log out
            </button>
          </div>
        </div>
      </header>

      {isDesktop && !sidebarHidden && <AppSidebar variant="rail" />}
      {drawerShown && <AppSidebar variant="drawer" onNavigate={closeDrawerAndRefocus} onClose={closeDrawerAndRefocus} panelRef={panelRef} />}

      {/* Content column (sits right of the sidebar) */}
      <div inert={drawerShown} className={`flex min-w-0 flex-1 flex-col transition-[padding] duration-200 motion-reduce:transition-none ${sidebarHidden ? '' : 'md:pl-[240px]'}`}>
        <main className="flex-1">
          <Outlet />
        </main>

        {/* Footer */}
        <footer className="border-t border-blue-400/10 bg-slate-950/80 py-3 text-center text-[12.6px] text-slate-600">
          AckIntel AI - Acknowledgement Document Intelligence
        </footer>
      </div>
    </div>
  )
}
