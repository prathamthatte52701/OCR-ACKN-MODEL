import { useCallback, useEffect, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAdminAuth } from '../context/AdminAuthContext'
import { useLayoutState } from '../hooks/useLayoutState'
import api from '../utils/api'
import { allowFocusBeat, createState } from '../utils/autoRefreshCore'
import { createTokens } from '../utils/chatAdminCore'
import { COUNTS_CHANGED_EVENT, notifyAdminTick } from '../utils/events'
import AdminChat from './chat/AdminChat'
import Sidebar from './Sidebar'
import TopBar from './TopBar'

const HEARTBEAT_MS = 15000

// The shell of every admin page: fixed sidebar (a drawer below 1024px), top bar, page content.
// Counts (pending approvals, orphaned files) and the system status are REAL: they come from the
// API and refresh on the shell heartbeat (15 s, only while the tab is visible), the system status
// every 60 s, or at once when a page announces a change. The heartbeat also tells pages to refresh.
export default function AdminLayout() {
  const [drawerPath, setDrawerPath] = useState(null) // open only for the path it was opened on
  const [counts, setCounts] = useState({ pending: 0, passwordRequests: 0, orphaned: 0 })
  const [system, setSystem] = useState(null)
  const [chatUnread, setChatUnread] = useState({ count: 0, byUser: null })
  const { sidebarHidden, toggleSidebar, chatOpen, chatDocked, toggleChat, closeChat } = useLayoutState()
  const { user, logout } = useAdminAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const menuButton = useRef(null)
  const chatButton = useRef(null)
  const chatPanel = useRef(null)
  const refocusChat = useRef(false)
  const drawerOpen = drawerPath === location.pathname
  const setDrawerOpen = useCallback((open) => setDrawerPath(open ? location.pathname : null), [location.pathname])

  const [unreadTokens] = useState(createTokens) // a slow older answer must not put an old count back
  const loadCounts = useCallback(() => {
    api.get('/admin/users', { params: { limit: 1, status: 'pending' } })
      .then((res) => setCounts((c) => ({ ...c, pending: res.data.pendingCount || 0, passwordRequests: res.data.passwordRequestCount || 0 })))
      .catch(() => {})
    api.get('/admin/orphaned-files', { params: { limit: 1 } })
      .then((res) => setCounts((c) => ({ ...c, orphaned: res.data.totalOrphanedFiles || 0 })))
      .catch(() => {})
    const token = unreadTokens.next()
    api.get('/chat/unread')
      .then((res) => { if (unreadTokens.isCurrent(token)) setChatUnread({ count: res.data.count || 0, byUser: res.data.byUser || [] }) })
      .catch(() => {})
  }, [unreadTokens])

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
    const visible = () => document.visibilityState === 'visible'
    const beat = () => { loadCounts(); notifyAdminTick() }
    const focusGate = createState()
    const wake = () => { if (visible() && allowFocusBeat(focusGate, Date.now())) beat() }
    loadCounts()
    loadSystem()
    const t1 = setInterval(() => { if (visible()) beat() }, HEARTBEAT_MS)
    const t2 = setInterval(() => { if (visible()) loadSystem() }, 60000)
    window.addEventListener(COUNTS_CHANGED_EVENT, loadCounts)
    window.addEventListener('focus', wake)
    document.addEventListener('visibilitychange', wake)
    return () => {
      clearInterval(t1)
      clearInterval(t2)
      window.removeEventListener(COUNTS_CHANGED_EVENT, loadCounts)
      window.removeEventListener('focus', wake)
      document.removeEventListener('visibilitychange', wake)
    }
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

  // Overlay chat (below 1280 px): same treatment as the menu drawer - one overlay at a time, the page
  // behind it inert, body scroll locked, Escape closes and gives focus back to the Chat button.
  const chatOverlay = chatOpen && !chatDocked
  const closeChatAndRefocus = useCallback(() => {
    refocusChat.current = true
    closeChat()
  }, [closeChat])
  useEffect(() => {
    if (!chatOpen && refocusChat.current) {
      refocusChat.current = false
      chatButton.current?.focus()
    }
  }, [chatOpen])
  useEffect(() => {
    if (!chatOverlay) return undefined
    // a dialog opened from the panel (clear chat) handles its own Escape
    const onKey = (e) => { if (e.key === 'Escape' && !document.querySelector('[data-admin-modal]')) closeChatAndRefocus() }
    window.addEventListener('keydown', onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    chatPanel.current?.focus()
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [chatOverlay, closeChatAndRefocus])

  function handleToggleChat() {
    if (!chatDocked && !chatOpen) setDrawerOpen(false)
    toggleChat()
  }
  function handleOpenMenu() {
    if (!chatDocked) closeChat()
    setDrawerOpen(true)
  }

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }
  const closeDrawer = () => setDrawerOpen(false)

  return (
    <div className="theme-admin min-h-screen">
      {/* Hidden at lg+: slid off-screen and invisible, so keyboard focus cannot reach its links */}
      <aside id="admin-sidebar" inert={chatOverlay} aria-hidden={sidebarHidden || undefined} className={`fixed inset-y-0 left-0 z-40 hidden w-[260px] border-r border-[var(--line-soft)] bg-[rgba(8,11,36,0.92)] lg:block lg:transition-[transform,visibility] lg:duration-200 motion-reduce:transition-none ${sidebarHidden ? 'lg:invisible lg:-translate-x-full' : ''}`}>
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

      {/* The top bar stays outside the size container (its menus must paint above the docked chat panel); only the page and footer get the chat's right padding. */}
      <div inert={chatOverlay} className={`flex min-h-screen flex-col lg:transition-[padding] lg:duration-200 motion-reduce:transition-none ${sidebarHidden ? 'lg:pl-0' : 'lg:pl-[260px]'}`}>
        <TopBar sidebarHidden={sidebarHidden} onToggleSidebar={toggleSidebar} user={user} pending={counts.pending + counts.passwordRequests} bellTo={counts.pending === 0 && counts.passwordRequests > 0 ? '/password-requests' : '/approvals'} onOpenMenu={handleOpenMenu} drawerOpen={drawerOpen} menuButtonRef={menuButton} onLogout={handleLogout} chatUnread={chatUnread.count} chatOpen={chatOpen} onToggleChat={handleToggleChat} chatButtonRef={chatButton} />
        <div className={`@container flex flex-1 flex-col lg:transition-[padding] lg:duration-200 motion-reduce:transition-none ${chatOpen && chatDocked ? 'pr-[var(--chat-w)]' : ''}`}>
          <main className="flex-1">
            <Outlet />
          </main>
          <footer className="border-t border-[var(--line-soft)] py-3 text-center text-[13px] text-[var(--muted)]">ACKN OCR - Admin</footer>
        </div>
      </div>

      <AdminChat adminId={user.id} open={chatOpen} overlay={chatOverlay} onClose={closeChatAndRefocus} panelRef={chatPanel} byUser={chatUnread.byUser} />
    </div>
  )
}
