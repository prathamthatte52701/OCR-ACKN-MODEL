import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Avatar } from './ui'

function SearchBox({ className = '' }) {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  function submit(e) {
    e.preventDefault()
    const term = q.trim().slice(0, 100)
    navigate(term ? `/users?q=${encodeURIComponent(term)}` : '/users')
  }
  return (
    <form onSubmit={submit} role="search" className={`relative ${className}`}>
      <button type="submit" aria-label="Search users" className="absolute left-1.5 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-lg text-[var(--muted)] hover:bg-white/10 hover:text-white">
        <svg className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" strokeLinecap="round" /></svg>
      </button>
      <input
        type="search"
        value={q}
        maxLength={100}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search users by name or email..."
        aria-label="Search users by name or email"
        className="input !pl-11"
      />
    </form>
  )
}

function UserMenu({ user, onLogout }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey) }
  }, [open])
  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open} aria-label="Account menu" className="flex items-center gap-3 rounded-2xl p-1.5 pr-2 hover:bg-white/5">
        <Avatar id={user?.id} name={user?.username} size={38} />
        <span className="hidden text-left leading-tight sm:block">
          <span className="block max-w-[140px] truncate text-[14px] font-bold text-white">{user?.username}</span>
          <span className="block text-[13px] text-[var(--muted)]">Administrator</span>
        </span>
        <svg className="hidden h-4 w-4 text-[var(--muted)] sm:block" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      {open && (
        <div role="menu" className="ui-card absolute right-0 top-full z-50 mt-2 w-48 overflow-hidden bg-[var(--surface-solid)] p-1.5">
          <Link role="menuitem" to="/profile" onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2 text-[14px] font-semibold text-white no-underline hover:bg-white/10">Profile</Link>
          <button role="menuitem" type="button" onClick={onLogout} className="block w-full rounded-lg px-3 py-2 text-left text-[14px] font-semibold text-rose-300 hover:bg-rose-500/10">Log out</button>
        </div>
      )}
    </div>
  )
}

export default function TopBar({ user, pending, bellTo = '/approvals', onOpenMenu, drawerOpen, menuButtonRef, onLogout }) {
  return (
    <header className="sticky top-0 z-30 border-b border-[var(--line-soft)] bg-[rgba(7,10,31,0.86)]">
      {/* Same max width as the page content, so the profile lines up with the page's right edge */}
      <div className="mx-auto flex h-16 w-full max-w-[1560px] items-center gap-3 px-4 sm:px-6 lg:px-8">
        <button ref={menuButtonRef} type="button" onClick={onOpenMenu} aria-label="Open menu" aria-expanded={drawerOpen} aria-controls="admin-drawer" className="btn btn-ghost !min-h-[40px] !px-3 shrink-0 lg:hidden">
          <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true"><path strokeLinecap="round" d="M4 6h16M4 12h16M4 18h16" /></svg>
        </button>
        <SearchBox className="min-w-0 max-w-[640px] flex-1" />
        <div className="ml-auto flex shrink-0 items-center gap-2 sm:gap-4">
          <Link to={bellTo} aria-label={pending > 0 ? `${pending} items need attention` : 'Approvals'} className="relative grid h-10 w-10 place-items-center rounded-xl border border-[var(--line)] bg-[rgba(124,108,255,0.08)] text-white hover:bg-[rgba(124,108,255,0.18)]">
            <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" /></svg>
            {pending > 0 && <span className="absolute -right-1.5 -top-1.5 grid min-w-[20px] place-items-center rounded-full bg-rose-500 px-1 text-[13px] font-bold leading-5 text-white">{pending > 99 ? '99+' : pending}</span>}
          </Link>
          <UserMenu user={user} onLogout={onLogout} />
        </div>
      </div>
    </header>
  )
}
