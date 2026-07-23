import { useState } from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { useAdminAuth } from '../context/AdminAuthContext'

const navLinks = [
  { to: '/', label: 'Dashboard', exact: true },
  { to: '/users', label: 'Users' },
  { to: '/documents', label: 'Documents' },
  { to: '/workbooks', label: 'Workbooks' },
  { to: '/logs', label: 'Logs' },
]

export default function AdminLayout() {
  const [menuOpen, setMenuOpen] = useState(false)
  const { user, logout } = useAdminAuth()
  const navigate = useNavigate()
  const initials = (user?.username || '??').slice(0, 2).toUpperCase()

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#04070d] text-slate-100">
      <header className="sticky top-0 z-50 border-b border-emerald-400/10 bg-slate-950/72 backdrop-blur-xl shadow-[0_14px_40px_rgba(2,8,23,0.28)]">
        <div className="mx-auto flex h-16 max-w-[1440px] items-center justify-between px-4 sm:px-6 lg:px-10">
          <NavLink to="/" className="group flex items-center gap-3 text-white no-underline">
            <span className="grid h-9 w-9 place-items-center rounded-xl border border-emerald-400/30 bg-emerald-500/15 text-[14.7px] font-black text-emerald-200 shadow-[0_0_28px_rgba(16,185,129,0.35)] transition-colors group-hover:border-teal-300/50">
              AD
            </span>
            <span className="leading-tight">
              <span className="block text-base font-bold tracking-tight">AckIntel AI</span>
              <span className="block text-[10.5px] font-medium uppercase tracking-[0.22em] text-slate-500">Admin Panel</span>
            </span>
          </NavLink>

          <nav className="hidden items-center gap-1 rounded-full border border-white/8 bg-white/[0.035] p-1 md:flex">
            {navLinks.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.exact}
                className={({ isActive }) =>
                  `relative rounded-full px-4 py-2 text-[14.7px] font-semibold transition-all no-underline ${
                    isActive
                      ? 'bg-emerald-500/15 text-emerald-100 shadow-[inset_0_-1px_0_rgba(52,211,153,0.55),0_0_24px_rgba(16,185,129,0.18)]'
                      : 'text-slate-400 hover:bg-white/[0.045] hover:text-slate-100'
                  }`
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>

          <div className="hidden items-center gap-3 md:flex">
            <NavLink
              to="/profile"
              className={({ isActive }) =>
                `flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] py-1 pl-1 pr-3 no-underline transition-colors hover:border-emerald-300/30 ${isActive ? 'border-emerald-300/30' : ''}`
              }
            >
              <span className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-emerald-500 to-teal-400 text-[12.6px] font-bold text-white">{initials}</span>
              <span className="text-[12.6px] font-semibold text-slate-300">{user?.username}</span>
            </NavLink>
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-full border border-white/10 bg-white/[0.035] px-4 py-2 text-[12.6px] font-bold text-slate-300 transition-colors hover:border-rose-300/30 hover:bg-rose-500/10 hover:text-rose-200"
            >
              Log out
            </button>
          </div>

          <button
            className="rounded-lg border border-white/10 bg-white/[0.04] p-2 text-slate-300 transition-colors hover:text-white md:hidden"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="Toggle menu"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {menuOpen
                ? <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                : <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />}
            </svg>
          </button>
        </div>

        <AnimatePresence>
          {menuOpen && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.18, ease: 'easeOut' }}
              className="overflow-hidden border-t border-emerald-400/10 bg-slate-950/95 md:hidden"
            >
              <div className="flex flex-col gap-1 px-4 py-3">
                {navLinks.map((link) => (
                  <NavLink
                    key={link.to}
                    to={link.to}
                    end={link.exact}
                    onClick={() => setMenuOpen(false)}
                    className={({ isActive }) =>
                      `rounded-lg px-3 py-2 text-[14.7px] font-semibold no-underline transition-colors ${
                        isActive ? 'bg-emerald-500/15 text-emerald-100' : 'text-slate-400 hover:bg-white/[0.045] hover:text-white'
                      }`
                    }
                  >
                    {link.label}
                  </NavLink>
                ))}
                <NavLink
                  to="/profile"
                  onClick={() => setMenuOpen(false)}
                  className={({ isActive }) =>
                    `rounded-lg px-3 py-2 text-[14.7px] font-semibold no-underline transition-colors ${
                      isActive ? 'bg-emerald-500/15 text-emerald-100' : 'text-slate-400 hover:bg-white/[0.045] hover:text-white'
                    }`
                  }
                >
                  Profile ({user?.username})
                </NavLink>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="rounded-lg px-3 py-2 text-left text-[14.7px] font-semibold text-rose-300 transition-colors hover:bg-rose-500/10"
                >
                  Log out
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-emerald-400/10 bg-slate-950/80 py-3 text-center text-[12.6px] text-slate-600">
        AckIntel AI - Admin Panel
      </footer>
    </div>
  )
}
