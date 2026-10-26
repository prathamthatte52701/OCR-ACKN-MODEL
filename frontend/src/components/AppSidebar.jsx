import { NavLink } from 'react-router-dom'
import { Activity, CircleHelp, FileSpreadsheet, FileText, LayoutDashboard, Upload, X } from 'lucide-react'

const navLinks = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, exact: true },
  { to: '/upload', label: 'Upload', icon: Upload },
  { to: '/documents', label: 'My Documents', icon: FileText },
  { to: '/export-history', label: 'Export History', icon: FileSpreadsheet },
  { to: '/my-activity', label: 'My Activity', icon: Activity },
  { to: '/help', label: 'Help', icon: CircleHelp },
]

function SidebarNav({ onNavigate }) {
  return (
    <nav aria-label="Main" className="flex-1 space-y-1.5 overflow-y-auto px-3 py-4">
      {navLinks.map(({ to, label, icon: Icon, exact }) => (
        <NavLink
          key={to}
          to={to}
          end={exact}
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-xl px-3 py-2 text-[14.7px] font-semibold no-underline transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ${
              isActive
                ? 'bg-blue-500/15 text-blue-100 shadow-[inset_0_-1px_0_rgba(96,165,250,0.55),0_0_24px_rgba(37,99,235,0.18)]'
                : 'text-slate-400 hover:bg-white/[0.045] hover:text-slate-100'
            }`
          }
        >
          <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
          <span className="min-w-0 truncate">{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}

// Desktop (>= 1024px): fixed rail under the top bar. Mobile: modal drawer.
export default function AppSidebar({ variant, onNavigate, onClose, panelRef }) {
  if (variant === 'drawer') {
    return (
      <div className="fixed inset-0 z-[60]">
        <button type="button" aria-hidden="true" tabIndex={-1} onClick={onClose} className="absolute inset-0 h-full w-full cursor-default bg-black/60" />
        <div
          ref={panelRef}
          id="app-sidebar"
          role="dialog"
          aria-modal="true"
          aria-label="Navigation"
          tabIndex={-1}
          className="relative flex h-full w-[240px] max-w-[85vw] flex-col border-r border-blue-400/10 bg-[#020817] shadow-2xl outline-none"
        >
          <div className="flex h-16 shrink-0 items-center justify-between border-b border-blue-400/10 px-4">
            <span className="text-base font-bold tracking-tight text-white">AckIntel AI</span>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close sidebar"
              className="rounded-lg border border-white/10 bg-white/[0.04] p-2 text-slate-300 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </div>
          <SidebarNav onNavigate={onNavigate} />
        </div>
      </div>
    )
  }

  return (
    <div id="app-sidebar" className="fixed bottom-0 left-0 top-16 z-40 flex w-[240px] flex-col border-r border-blue-400/10 bg-[#020817]">
      <SidebarNav onNavigate={onNavigate} />
    </div>
  )
}
