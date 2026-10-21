import { useCallback, useEffect, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAdminAuth } from '../context/AdminAuthContext'
import api from '../utils/api'
import { COUNTS_CHANGED_EVENT } from '../utils/events'
import Sidebar from './Sidebar'
import TopBar from './TopBar'

// The shell of every admin page: fixed sidebar (a drawer below 1024px), top bar, page content.
// Counts (pending approvals, orphaned files) and the system status are REAL: they come from the
// API and refresh every 30-60 s or at once when a page announces a change.
export default function AdminLayout() {
  const [drawerPath, setDrawerPath] = useState(null) // open only for the path it was opened on
  const [counts, setCounts] = useState({ pending: 0, passwordRequests: 0, orphaned: 0 })
  const [system, setSystem] = useState(null)
  const { user, logout } = useAdminAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const menuButton = useRef(null)
  const drawerOpen = drawerPath === location.pathname
  const setDrawerOpen = useCallback((open) => setDrawerPath(open ? location.pathname : null), [location.pathname])

  const loadCounts = useCallback(() => {
    api.get('/admin/users', { params: { limit: 1, status: 'pending' } })
      .then((res) => setCounts((c) => ({ ...c, pending: res.data.pendingCount || 0, passwordRequests: res.data.passwordRequestCount || 0 })))
      .catch(() => {})
    api.get('/admin/orphaned-files', { params: { limit: 1 } })
      .then((res) => setCounts((c) => ({ ...c, orphaned: res.data.totalOrphanedFiles || 0 })))
      .catch(() => {})
  }, [])

  const loadSystem = useCallback(() => {
    api.get('/admin/system')
      .then((res) => {
        const s = res.data
        if (!s.db?.ok) setSystem({ tone: 'bad', text: 'Database not reachable' })
        else if (s.ocrLockWedged) setSystem({ tone: 'warn', text: 'OCR engine stuck - restart the app' })
        else if (s.ocrEngine?.consecutiveFailures >= 3) setSystem({ tone: 'warn', text: `OCR engine failing (last: ${s.ocrEngine.lastErrorClass || 'unknown'}) - check the server log (backend\\logs\\app.log)` })
        else setSystem({ tone: 'ok', text: 'All services running' })
      })
      .catch(() => setSystem(null))
  }, [])

  useEffect(() => {
    loadCounts()
    loadSystem()
    const t1 = setInterval(loadCounts, 30000)
    const t2 = setInterval(loadSystem, 60000)
    window.addEventListener(COUNTS_CHANGED_EVENT, loadCounts)
    return () => { clearInterval(t1); clearInterval(t2); window.removeEventListener(COUNTS_CHANGED_EVENT, loadCounts) }
  }, [loadCounts, loadSystem])

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
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[260px] border-r border-[var(--line-soft)] bg-[rgba(8,11,36,0.92)] lg:block">
        <Sidebar counts={counts} system={system} />
      </aside>

      {drawerOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button type="button" aria-label="Close menu" onClick={closeDrawer} className="absolute inset-0 bg-black/70" />
          <aside id="admin-drawer" role="dialog" aria-modal="true" aria-label="Admin menu" className="absolute inset-y-0 left-0 w-72 max-w-[85vw] border-r border-[var(--line)] bg-[#0a0d2c]">
            <Sidebar counts={counts} system={system} onNavigate={closeDrawer} />
          </aside>
        </div>
      )}

      <div className="flex min-h-screen flex-col lg:pl-[260px]">
        <TopBar user={user} pending={counts.pending + counts.passwordRequests} bellTo={counts.pending === 0 && counts.passwordRequests > 0 ? '/password-requests' : '/approvals'} onOpenMenu={() => setDrawerOpen(true)} drawerOpen={drawerOpen} menuButtonRef={menuButton} onLogout={handleLogout} />
        <main className="flex-1">
          <Outlet />
        </main>
        <footer className="border-t border-[var(--line-soft)] py-3 text-center text-[13px] text-[var(--muted)]">ACKN OCR - Admin</footer>
      </div>
    </div>
  )
}
