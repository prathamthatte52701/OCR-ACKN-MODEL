// Shared building blocks of the ACKN admin design system. Styling lives in index.css (.theme-admin).
import { Link } from 'react-router-dom'
import { avatarGradient, initialsOf } from '../utils/avatar'
import { Sparkline } from './charts'
import { PALETTE } from '../utils/palette'

export function Card({ as: Tag = 'section', className = '', variant = '', children, ...rest }) {
  const v = variant === 'flat' ? 'ui-card-flat' : variant === 'danger' ? 'ui-card-danger' : ''
  return <Tag className={`ui-card ${v} ${className}`} {...rest}>{children}</Tag>
}

export function PageHeader({ title, subtitle, actions, children }) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[30px] font-extrabold leading-tight tracking-tight text-white sm:text-[34px]">{title}</h1>
        {subtitle && <p className="mt-1 text-[15px] text-[var(--violet-2)]">{subtitle}</p>}
        {children}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-3">{actions}</div>}
    </header>
  )
}

const TONES = {
  green: 'bg-emerald-400/12 text-emerald-300 border-emerald-400/35',
  amber: 'bg-amber-400/12 text-amber-300 border-amber-400/35',
  red: 'bg-rose-400/12 text-rose-300 border-rose-400/40',
  violet: 'bg-violet-400/14 text-violet-200 border-violet-400/40',
  blue: 'bg-blue-400/12 text-blue-300 border-blue-400/35',
  teal: 'bg-teal-400/12 text-teal-300 border-teal-400/35',
  neutral: 'bg-white/5 text-slate-200 border-white/15',
}

export function Badge({ tone = 'neutral', dot = false, children, className = '' }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[13px] font-semibold ${TONES[tone] || TONES.neutral} ${className}`}>
      {dot && <span className="h-2 w-2 rounded-full bg-current" aria-hidden="true" />}
      {children}
    </span>
  )
}

export function Avatar({ id, name, size = 36, className = '' }) {
  return (
    <span
      className={`grid shrink-0 place-items-center rounded-full font-bold text-white ${className}`}
      style={{ width: size, height: size, background: avatarGradient(id || name), fontSize: Math.max(13, size * 0.38) }}
      aria-hidden="true"
    >
      {initialsOf(name)}
    </span>
  )
}

export function Skeleton({ className = '', style }) {
  return <div className={`skeleton ${className}`} style={style} aria-hidden="true" />
}

export function EmptyState({ title, hint, action }) {
  return (
    <div className="grid place-items-center px-4 py-12 text-center">
      <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl border border-[var(--line)] bg-[rgba(124,108,255,0.1)] text-[var(--violet-2)]" aria-hidden="true">
        <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M20 13V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7m16 0v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-5m16 0h-4l-2 3h-4l-2-3H4" /></svg>
      </div>
      <p className="text-[15px] font-semibold text-white">{title}</p>
      {hint && <p className="mt-1 max-w-sm text-[14px] text-[var(--muted)]">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorState({ message = 'Something went wrong.', onRetry }) {
  return (
    <div role="alert" className="grid place-items-center px-4 py-10 text-center">
      <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl border border-rose-400/40 bg-rose-400/10 text-rose-300" aria-hidden="true">
        <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /></svg>
      </div>
      <p className="text-[15px] font-semibold text-white">{message}</p>
      {onRetry && <button type="button" onClick={onRetry} className="btn btn-ghost btn-sm mt-4">Try again</button>}
    </div>
  )
}

const TILE_FOR = { violet: 'tile-violet', blue: 'tile-blue', teal: 'tile-teal', amber: 'tile-amber', pink: 'tile-pink' }
const SPARK_FOR = { violet: PALETTE.violetSoft, blue: PALETTE.blue, teal: PALETTE.teal, amber: PALETTE.orange, pink: PALETTE.pink }

// Gradient stat card: icon, label, big value, optional trend line and sparkline.
export function StatCard({ label, value, tone = 'violet', icon, trend, sparkline, to, loading = false, children }) {
  const body = (
    <div className={`ui-card ${TILE_FOR[tone] || ''} flex h-full flex-col justify-between p-5`}>
      <div className="flex items-start gap-4">
        {icon && <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-white/20 bg-white/10 text-white" aria-hidden="true">{icon}</span>}
        <div className="min-w-0">
          <div className="text-[14px] font-semibold text-white/85">{label}</div>
          {loading ? <Skeleton className="mt-2 h-8 w-24" /> : <div className="mt-1 text-[32px] font-extrabold leading-none text-white">{value}</div>}
          {trend && !loading && <div className="mt-2 text-[13px] font-semibold text-white/80">{trend}</div>}
        </div>
      </div>
      {sparkline && <Sparkline values={sparkline} color={SPARK_FOR[tone]} width={240} height={46} className="mt-3 w-full" />}
      {children}
    </div>
  )
  return to ? <Link to={to} className="block h-full no-underline transition-transform hover:-translate-y-0.5">{body}</Link> : body
}

export function ChartCard({ title, action, children, className = '' }) {
  return (
    <Card className={`p-5 ${className}`} aria-label={title}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-[16px] font-bold text-white">{title}</h2>
        {action}
      </div>
      {children}
    </Card>
  )
}

export function Trend({ current, previous, suffix = 'vs previous 7 days' }) {
  if (current == null || previous == null) return null
  const diff = current - previous
  if (diff === 0) return <span>No change {suffix}</span>
  return <span>{diff > 0 ? '▲ +' : '▼ '}{diff} {suffix}</span>
}

// Thin wrappers so every table in the app shares the same markup.
export function DataTable({ children, className = '', minWidth = 640, ...rest }) {
  return (
    <div className={`overflow-x-auto ${className}`}>
      <table className="ui-table" style={{ minWidth }} {...rest}>{children}</table>
    </div>
  )
}
