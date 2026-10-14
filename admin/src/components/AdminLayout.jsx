import { useCallback, useEffect, useRef, useState } from 'react'
import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAdminAuth } from '../context/AdminAuthContext'
import api from '../utils/api'

// Anything that changes the pending-approval / orphaned-file counts (Approve on the Dashboard,
// ...) dispatches this so the sidebar badges refresh at once instead of on the 30 s timer.
export const COUNTS_CHANGED_EVENT = 'admin:counts-changed'

function Icon({ d }) {
  return (
    <svg className="h-[18px] w-[18px] shrink-0" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24" aria-hidden="true">
      <path d={d} />
    </svg>
  )
}

const ICONS = {
  dashboard: 'M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z',
  users: 'M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM21 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
  documents: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h8',
  workbooks: 'M4 4h16v16H4zM4 9h16M4 14h16M10 4v16',
  logs: 'M4 6h16M4 12h16M4 18h10',
  orphaned: 'M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01',
  maintenance: 'M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5',
}

const NAV = [
  { to: '/', label: 'Dashboard', icon: 'dashboard', exact: true },
  { to: '/users', label: 'Users', icon: 'users', badge: 'pending' },
  { to: '/documents', label: 'Documents', icon: 'documents' },
  { to: '/workbooks', label: 'Workbooks', icon: 'workbooks' },
  { to: '/logs', label: 'Logs', icon: 'logs' },
  { to: '/orphaned-files', label: 'Orphaned Files', icon: 'orphaned', badge: 'orphaned' },
]

function Badge({ count }) {
  if (!count) return null
  return (
    <span className="ml-auto rounded-full bg-amber-400 px-2 py-0.5 text-[13px] font-black leading-none text-slate-950" aria-label={`${count} waiting`}>
      {count > 99 ? '99+' : count}
    </span>
  )
}

function SidebarContent({ counts, user, onNavigate, onLogout }) {
  const initials = (user?.username || '??').slice(0, 2).toUpperCase()
  return (
    <div className="flex h-full flex-col">
      <NavLink to="/" onClick={onNavigate} className="flex items-center gap-3 px-5 py-5 text-white no-underline">
        <span className="grid h-10 w-10 place-items-center rounded-xl border border-[var(--hud-green)]/40 bg-[var(--hud-green)]/10 text-[14px] font-black text-[var(--hud-green)] shadow-[0_0_22px_rgba(43,255,136,0.25)]">AD</span>
        <span className="leading-tight">
          <span className="block text-[16px] font-bold tracking-tight">AckIntel AI</span>
          <span className="block text-[13px] font-semibold uppercase tracking-[0.18em] text-[var(--hud-muted)]">Admin</span>
        </span>
      </NavLink>

      <nav aria-label="Admin" className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.exact} onClick={onNavigate} className="hud-nav-link">
            <Icon d={ICONS[item.icon]} />
            <span>{item.label}</span>
            {item.badge && <Badge count={counts[item.badge]} />}
          </NavLink>
        ))}
      </nav>

      <div className="space-y-2 border-t border-[var(--hud-border)] px-3 pb-4 pt-3">
        <NavLink to="/maintenance" onClick={onNavigate} className="hud-nav-link hud-nav-danger">
          <Icon d={ICONS.maintenance} />
          <span>Maintenance</span>
        </NavLink>
        <div className="flex items-center gap-2 rounded-xl border border-[var(--hud-border)] bg-black/20 p-2">
          <NavLink to="/profile" onClick={onNavigate} className="flex min-w-0 flex-1 items-center gap-2 rounded-lg p-1 text-[var(--hud-text)] no-underline hover:bg-white/5" title="Profile">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-[var(--hud-green)] to-[var(--hud-cyan)] text-[13px] font-black text-slate-950">{initials}</span>
            <span className="truncate text-[14px] font-semibold">{user?.username}</span>
          </NavLink>
          <button type="button" onClick={onLogout} className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-[13px] font-bold text-[var(--hud-text)] transition-colors hover:border-rose-300/40 hover:bg-rose-500/10 hover:text-rose-200">
            Log out
          </button>
        </div>
      </div>
    </div>
  )
}

export default function AdminLayout() {
  // The drawer is open only for the path it was opened on, so any navigation (even browser Back)
  // closes it without an effect.
  const [drawerPath, setDrawerPath] = useState(null)
  const [counts, setCounts] = useState({ pending: 0, orphaned: 0 })
  const { user, logout } = useAdminAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const menuButton = useRef(null)
  const drawerOpen = drawerPath === location.pathname
  const setDrawerOpen = useCallback((open) => setDrawerPath(open ? location.pathname : null), [location.pathname])

  const loadCounts = useCallback(() => {
    api.get('/admin/users', { params: { limit: 1, status: 'pending' } })
      .then((res) => setCounts((c) => ({ ...c, pending: res.data.pendingCount || 0 })))
      .catch(() => {})
    api.get('/admin/orphaned-files', { params: { limit: 1 } })
      .then((res) => setCounts((c) => ({ ...c, orphaned: res.data.totalOrphanedFiles || 0 })))
      .catch(() => {})
  }, [])

  useEffect(() => {
    loadCounts()
    const timer = setInterval(loadCounts, 30000)
    window.addEventListener(COUNTS_CHANGED_EVENT, loadCounts)
    return () => { clearInterval(timer); window.removeEventListener(COUNTS_CHANGED_EVENT, loadCounts) }
  }, [loadCounts])

  // Escape and growing into the desktop layout also close it.
  useEffect(() => {
    if (!drawerOpen) return undefined
    const onKey = (e) => { if (e.key === 'Escape') { setDrawerOpen(false); menuButton.current?.focus() } }
    const mq = window.matchMedia('(min-width: 1024px)')
    const onChange = (e) => { if (e.matches) setDrawerOpen(false) }
    window.addEventListener('keydown', onKey)
    mq.addEventListener('change', onChange)
    return () => { window.removeEventListener('keydown', onKey); mq.removeEventListener('change', onChange) }
  }, [drawerOpen, setDrawerOpen])

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  const closeDrawer = () => setDrawerOpen(false)

  return (
    <div className="theme-admin min-h-screen">
      {/* Desktop: fixed sidebar */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 border-r border-[var(--hud-border)] bg-[#050d0a]/90 backdrop-blur lg:block">
        <SidebarContent counts={counts} user={user} onLogout={handleLogout} />
      </aside>

      {/* Below 1024px: top bar + slide-in drawer */}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-[var(--hud-border)] bg-[#050d0a]/90 px-4 backdrop-blur lg:hidden">
        <button
          ref={menuButton}
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="Open menu"
          aria-expanded={drawerOpen}
          aria-controls="admin-drawer"
          className="rounded-lg border border-[var(--hud-border)] p-2 text-[var(--hud-text)]"
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" /></svg>
        </button>
        <span className="text-[16px] font-bold">AckIntel AI <span className="text-[var(--hud-green)]">Admin</span></span>
        {counts.pending > 0 && <span className="ml-auto rounded-full bg-amber-400 px-2 py-0.5 text-[13px] font-black text-slate-950">{counts.pending}</span>}
      </header>

      {drawerOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button type="button" aria-label="Close menu" onClick={closeDrawer} className="absolute inset-0 bg-black/70" />
          <aside id="admin-drawer" role="dialog" aria-modal="true" aria-label="Admin menu" className="absolute inset-y-0 left-0 w-72 max-w-[85vw] border-r border-[var(--hud-border)] bg-[#050d0a]">
            <SidebarContent counts={counts} user={user} onNavigate={closeDrawer} onLogout={handleLogout} />
          </aside>
        </div>
      )}

      <div className="flex min-h-screen flex-col lg:pl-64">
        <main className="flex-1">
          <Outlet />
        </main>
        <footer className="border-t border-[var(--hud-border)] py-3 text-center text-[13px] text-[var(--hud-muted)]">
          AckIntel AI - Admin Panel
        </footer>
      </div>
    </div>
  )
}
