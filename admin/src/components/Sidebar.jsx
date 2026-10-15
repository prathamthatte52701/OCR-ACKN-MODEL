import { NavLink } from 'react-router-dom'

function Icon({ d }) {
  return (
    <svg className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24" aria-hidden="true">
      <path d={d} />
    </svg>
  )
}

const ICONS = {
  dashboard: 'M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z',
  users: 'M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM21 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
  approvals: 'M12 3 4 6v6c0 5 3.4 8.4 8 9 4.6-.6 8-4 8-9V6zM9 12l2 2 4-4',
  documents: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h8',
  workbooks: 'M4 4h16v16H4zM4 9h16M4 14h16M10 4v16',
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  orphaned: 'M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01',
  maintenance: 'M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z',
}

const NAV = [
  { to: '/', label: 'Dashboard', icon: 'dashboard', exact: true },
  { to: '/users', label: 'Users', icon: 'users' },
  { to: '/approvals', label: 'Approvals', icon: 'approvals', badge: 'pending' },
  { to: '/documents', label: 'Documents', icon: 'documents' },
  { to: '/workbooks', label: 'Workbooks', icon: 'workbooks' },
  { to: '/logs', label: 'Activity', icon: 'activity' },
  { to: '/orphaned-files', label: 'Orphaned files', icon: 'orphaned', badge: 'orphaned' },
  { to: '/maintenance', label: 'Maintenance', icon: 'maintenance' },
]

function CountBadge({ count }) {
  if (!count) return null
  return (
    <span className="ml-auto rounded-full bg-rose-500 px-2 py-0.5 text-[13px] font-bold leading-none text-white" aria-label={`${count} waiting`}>
      {count > 99 ? '99+' : count}
    </span>
  )
}

// status = null (unknown) | { tone: 'ok'|'warn'|'bad', text }
function SystemCard({ status, onNavigate }) {
  const tone = status?.tone || 'unknown'
  const dot = tone === 'ok' ? 'bg-emerald-400 shadow-[0_0_10px_#34d399]' : tone === 'warn' ? 'bg-amber-400' : tone === 'bad' ? 'bg-rose-400' : 'bg-slate-500'
  return (
    <div className="ui-card ui-card-flat p-4">
      <div className="flex items-center gap-2 text-[14px] font-semibold text-white">
        <span className={`h-2.5 w-2.5 rounded-full ${dot}`} aria-hidden="true" />
        System status
      </div>
      <p className="mt-1 text-[13px] text-[var(--muted)]">{status ? status.text : 'Status unavailable'}</p>
      <NavLink to="/maintenance" onClick={onNavigate} className="btn btn-ghost btn-sm mt-3 w-full no-underline">Open Maintenance</NavLink>
    </div>
  )
}

export default function Sidebar({ counts, system, onNavigate }) {
  return (
    <div className="flex h-full flex-col">
      <NavLink to="/" onClick={onNavigate} className="flex items-center gap-3 px-5 py-5 text-white no-underline" aria-label="ACKN OCR home">
        <svg className="h-9 w-9" viewBox="0 0 36 36" aria-hidden="true">
          <defs><linearGradient id="ackn-logo" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#a78bfa" /><stop offset="1" stopColor="#4f6bff" /></linearGradient></defs>
          <path d="M18 3 4 33h7l2.4-5.6h9.2L25 33h7z M15.6 22.4 18 16.6l2.4 5.8z" fill="url(#ackn-logo)" fillRule="evenodd" />
        </svg>
        <span className="text-[20px] font-extrabold tracking-tight">ACKN <span className="text-[var(--violet-2)]">OCR</span></span>
      </NavLink>

      <nav aria-label="Admin" className="flex-1 space-y-1.5 overflow-y-auto px-3 py-2">
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.exact} onClick={onNavigate} className="nav-link">
            <Icon d={ICONS[item.icon]} />
            <span>{item.label}</span>
            {item.badge && <CountBadge count={counts[item.badge]} />}
          </NavLink>
        ))}
      </nav>

      <div className="px-3 pb-4 pt-3">
        <SystemCard status={system} onNavigate={onNavigate} />
      </div>
    </div>
  )
}
