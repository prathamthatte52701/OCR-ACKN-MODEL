import { Link } from 'react-router-dom'

// Tab strip shared by Users, Approvals and Password requests. Password requests is its own
// tab with its own badge - never folded into Pending/Rejected.
const TABS = [
  { key: 'users', to: '/users', label: 'Users' },
  { key: 'approvals', to: '/approvals', label: 'Approvals', badge: 'pending' },
  { key: 'requests', to: '/password-requests', label: 'Password requests', badge: 'requests' },
]

export default function UsersTabs({ active, pending = 0, requests = 0 }) {
  const counts = { pending, requests }
  return (
    <nav aria-label="Users sections" className="mb-5 flex flex-wrap gap-2">
      {TABS.map((t) => {
        const n = t.badge ? counts[t.badge] : 0
        return (
          <Link
            key={t.key}
            to={t.to}
            aria-current={active === t.key ? 'page' : undefined}
            className={`flex items-center gap-2 rounded-full border px-4 py-1.5 text-[14px] font-semibold no-underline transition-colors ${active === t.key ? 'border-violet-300/60 bg-violet-500 text-white' : 'border-[var(--line)] bg-white/5 text-[var(--muted)] hover:text-white'}`}
          >
            {t.label}
            {n > 0 && <span className="rounded-full bg-rose-500 px-2 py-0.5 text-[12px] font-bold leading-none text-white">{n > 99 ? '99+' : n}</span>}
          </Link>
        )
      })}
    </nav>
  )
}
