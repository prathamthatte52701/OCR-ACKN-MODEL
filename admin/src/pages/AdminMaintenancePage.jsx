import { Link } from 'react-router-dom'
import BackButton from '../components/BackButton'
import { Badge, Card, ChartCard, EmptyState, ErrorState, PageHeader, Skeleton, StatCard, Trend } from '../components/ui'
import { Donut } from '../components/charts'
import { PALETTE } from '../utils/palette'
import { relativeTime } from '../utils/activity'
import GlobalNukePanel from './maintenance/GlobalNukePanel'
import WarningIcon from './maintenance/WarningIcon'
import useApi from './maintenance/useApi'
import { describeMaintenance, formatBytes, formatUptime, localDateTime, plural } from './maintenance/format'

const DOT_FOR = { red: 'bg-rose-400', amber: 'bg-amber-400', blue: 'bg-blue-400', teal: 'bg-teal-400', violet: 'bg-violet-400', neutral: 'bg-slate-400' }

function Icon({ children }) {
  return (
    <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  )
}

const DbIcon = () => (
  <Icon>
    <ellipse cx="12" cy="5" rx="8" ry="3" />
    <path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
  </Icon>
)
const DocIcon = () => (
  <Icon>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5M9 13h6M9 17h6" />
  </Icon>
)
const ClockIcon = () => (
  <Icon>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </Icon>
)
const RefreshIcon = ({ spin }) => (
  <svg className={`h-4 w-4 ${spin ? 'animate-spin' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 12a9 9 0 1 1-3-6.7M21 4v5h-5" />
  </svg>
)

// Health pill computed from GET /admin/system. Never assumes "healthy".
function StatusPill({ sys }) {
  if (sys.loading && !sys.data) return <Skeleton className="h-8 w-36 !rounded-full" />
  let tone = 'neutral'
  let text = 'Status unavailable'
  if (!sys.error && sys.data) {
    if (!sys.data.db?.ok) {
      tone = 'red'
      text = 'Database not reachable'
    } else if (sys.data.ocrLockWedged) {
      tone = 'amber'
      text = 'OCR engine stuck - restart the app'
    } else if (sys.data.ocrEngine?.consecutiveFailures >= 3) {
      tone = 'amber'
      text = `OCR engine failing (last: ${sys.data.ocrEngine.lastErrorClass || 'unknown'}) - check the server log (backend\\logs\\app.log)`
    } else {
      tone = 'green'
      text = 'System healthy'
    }
  }
  const ping = sys.data?.db?.ok ? `Database ping ${sys.data.db.pingMs} ms` : undefined
  return (
    <span role="status" title={ping}>
      <Badge tone={tone} dot className="!px-3.5 !py-1.5 !text-[14px]">{text}</Badge>
    </span>
  )
}

function WidgetError({ message, onRetry, className = '' }) {
  return (
    <Card className={`p-5 ${className}`}>
      <ErrorState message={message} onRetry={onRetry} />
    </Card>
  )
}

function StorageCard({ sys }) {
  if (sys.error && !sys.data) return <WidgetError message={sys.error} onRetry={sys.reload} />
  const docs = sys.data?.storage?.documentFiles || { bytes: 0, count: 0 }
  const books = sys.data?.storage?.workbookFiles || { bytes: 0, count: 0 }
  const total = docs.bytes + books.bytes
  return (
    <StatCard
      label="Storage used"
      tone="violet"
      icon={<DbIcon />}
      loading={sys.loading && !sys.data}
      value={formatBytes(total)}
      trend={`${plural(docs.count, 'document file', 'document files')}, ${plural(books.count, 'workbook', 'workbooks')}`}
    >
      {sys.data && (
        <div
          className="mt-4 flex h-2 overflow-hidden rounded-full bg-white/10"
          role="img"
          aria-label={`Document files ${formatBytes(docs.bytes)}, workbook files ${formatBytes(books.bytes)}`}
        >
          {total > 0 && (
            <>
              <span style={{ width: `${(docs.bytes / total) * 100}%`, background: PALETTE.violetSoft }} />
              <span style={{ width: `${(books.bytes / total) * 100}%`, background: PALETTE.blue }} />
            </>
          )}
        </div>
      )}
    </StatCard>
  )
}

function ProcessedCard({ tel }) {
  if (tel.error && !tel.data) return <WidgetError message={tel.error} onRetry={tel.reload} />
  const p = tel.data?.processedDocuments
  const docs = tel.data?.series?.documents || []
  return (
    <StatCard
      label="Processed documents"
      tone="blue"
      icon={<DocIcon />}
      loading={tel.loading && !tel.data}
      value={(p?.total ?? 0).toLocaleString()}
      trend={p ? <Trend current={p.current} previous={p.previous} /> : null}
      sparkline={docs.length > 1 ? docs.slice(-14) : undefined}
    />
  )
}

function UptimeCard({ sys }) {
  if (sys.error && !sys.data) return <WidgetError message={sys.error} onRetry={sys.reload} className="sm:col-span-2 xl:col-span-1" />
  const since = sys.data?.serverStartedAt ? localDateTime(sys.data.serverStartedAt) : ''
  return (
    <div className="sm:col-span-2 xl:col-span-1">
      <StatCard
        label="Server uptime"
        tone="teal"
        icon={<ClockIcon />}
        loading={sys.loading && !sys.data}
        value={formatUptime(sys.data?.uptimeSeconds)}
        trend={since ? `Since ${since}` : null}
      />
    </div>
  )
}

function StorageOverview({ sys }) {
  const action = sys.data?.checkedAt ? <span className="text-[13px] text-[var(--muted)]">Updated {relativeTime(sys.data.checkedAt)}</span> : null
  return (
    <ChartCard title="Storage overview" action={action}>
      {sys.loading && !sys.data ? (
        <div className="flex flex-wrap items-center gap-6">
          <Skeleton className="h-[170px] w-[170px] !rounded-full" />
          <div className="min-w-[180px] flex-1 space-y-3">
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-full" />
          </div>
        </div>
      ) : sys.error && !sys.data ? (
        <ErrorState message={sys.error} onRetry={sys.reload} />
      ) : (
        <StorageBreakdown storage={sys.data?.storage} />
      )}
    </ChartCard>
  )
}

function StorageBreakdown({ storage }) {
  const docs = storage?.documentFiles || { bytes: 0, count: 0 }
  const books = storage?.workbookFiles || { bytes: 0, count: 0 }
  const total = docs.bytes + books.bytes
  if (total === 0) {
    return <EmptyState title="Nothing stored yet" hint="Document files and workbooks will show up here once users upload and export." />
  }
  const rows = [
    { name: 'Document files', color: PALETTE.violetSoft, ...docs },
    { name: 'Workbook files', color: PALETTE.blue, ...books },
  ]
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-5 sm:justify-start">
      <Donut segments={rows.map((r) => ({ name: r.name, value: r.bytes, color: r.color }))} total={formatBytes(total)} centerLabel="Used storage" />
      <ul className="m-0 min-w-[200px] flex-1 list-none p-0">
        {rows.map((r) => (
          <li key={r.name} className="flex items-center gap-3 border-b border-[var(--line-soft)] py-3 last:border-b-0">
            <span className="h-3 w-3 shrink-0 rounded-full" style={{ background: r.color }} aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14px] font-semibold text-white">{r.name}</span>
              <span className="block text-[13px] text-[var(--muted)]">{plural(r.count, 'file', 'files')}</span>
            </span>
            <span className="whitespace-nowrap text-[14px] font-bold text-white">{formatBytes(r.bytes)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ToolRow({ icon, title, description, to, cta }) {
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-[var(--line-soft)] py-4 first:pt-1 last:border-b-0 last:pb-1">
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-[var(--line)] bg-[rgba(124,108,255,0.12)] text-[var(--violet-2)]" aria-hidden="true">
        {icon}
      </span>
      <div className="min-w-0 flex-1 basis-48">
        <p className="m-0 text-[15px] font-semibold text-white">{title}</p>
        <div className="mt-0.5 text-[13px] leading-5 text-[var(--muted)]">{description}</div>
      </div>
      <Link to={to} className="btn btn-ghost btn-sm shrink-0">{cta}</Link>
    </li>
  )
}

function MaintenanceTools({ tel }) {
  const orphaned = tel.data?.orphanedFiles
  let orphanText = 'Stored files that failed to delete and need review.'
  if (tel.loading && !tel.data) orphanText = <Skeleton className="mt-1 h-4 w-48" />
  else if (typeof orphaned === 'number') orphanText = `${plural(orphaned, 'stored file', 'stored files')} that failed to delete and need review.`
  return (
    <ChartCard title="Maintenance tools">
      <ul className="m-0 list-none p-0">
        <ToolRow
          icon={<Icon><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M12 11v3M12 17h.01" /></Icon>}
          title="Orphaned files"
          description={orphanText}
          to="/orphaned-files"
          cta="Review"
        />
        <ToolRow
          icon={<DocIcon />}
          title="Documents"
          description="Remove stored original files for single documents."
          to="/documents"
          cta="Open documents"
        />
        <ToolRow
          icon={<ClockIcon />}
          title="Activity log"
          description="See every admin and user action, including deletes and purges."
          to="/logs"
          cta="Open log"
        />
      </ul>
    </ChartCard>
  )
}

function ActivityTimeline({ tel }) {
  const items = tel.data?.recentMaintenance || []
  return (
    <ChartCard title="Maintenance activity" action={<Link to="/logs" className="text-[13px] font-semibold text-[var(--violet-2)] hover:text-white">View all</Link>}>
      {tel.loading && !tel.data ? (
        <div className="space-y-4">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
        </div>
      ) : tel.error && !tel.data ? (
        <ErrorState message={tel.error} onRetry={tel.reload} />
      ) : items.length === 0 ? (
        <EmptyState title="No maintenance activity yet" hint="Deletes, file purges and orphaned-file actions will be listed here." />
      ) : (
        <ol className="m-0 list-none p-0">
          {items.map((it, i) => {
            const d = describeMaintenance(it)
            return (
              <li key={it.id} className="relative flex gap-3 pb-4 last:pb-0">
                {i < items.length - 1 && <span className="absolute left-[7px] top-5 h-[calc(100%-12px)] w-px bg-[var(--line)]" aria-hidden="true" />}
                <span className={`relative mt-1.5 h-[15px] w-[15px] shrink-0 rounded-full border-2 border-[var(--surface-solid)] ${DOT_FOR[d.tone] || DOT_FOR.neutral}`} aria-hidden="true" />
                <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-3 gap-y-1">
                  <div className="min-w-0 basis-52 flex-1">
                    <p className="m-0 break-words text-[14px] font-medium text-white">{d.text}</p>
                    <p className="m-0 text-[13px] text-[var(--muted)]" title={localDateTime(it.createdAt)}>{relativeTime(it.createdAt)}</p>
                  </div>
                  <Badge tone={d.tone}>{d.label}</Badge>
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </ChartCard>
  )
}

export default function AdminMaintenancePage() {
  const sys = useApi('/admin/system', 'Could not load system status.')
  const tel = useApi('/admin/telemetry', 'Could not load maintenance data.')
  const refreshing = sys.loading || tel.loading

  function refresh() {
    sys.reload()
    tel.reload()
  }

  return (
    <div className="mx-auto max-w-[1560px] px-4 py-6 sm:px-6 lg:px-8">
      <BackButton fallback="/" />
      <PageHeader
        title="Maintenance"
        subtitle="Monitor storage and manage data for ACKN OCR"
        actions={
          <>
            <StatusPill sys={sys} />
            <button type="button" onClick={refresh} disabled={refreshing} className="btn btn-ghost">
              <RefreshIcon spin={refreshing} />
              Refresh status
            </button>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <StorageCard sys={sys} />
        <ProcessedCard tel={tel} />
        <UptimeCard sys={sys} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <StorageOverview sys={sys} />
        <MaintenanceTools tel={tel} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <ActivityTimeline tel={tel} />
        <Card variant="danger" className="p-5" aria-label="Danger zone">
          <div className="mb-4 flex items-start gap-3">
            <WarningIcon className="mt-1 h-7 w-7 shrink-0 text-rose-300" />
            <div>
              <h2 className="text-[20px] font-extrabold text-rose-300">Danger zone</h2>
              <p role="alert" className="mt-1 text-[14px] font-semibold text-rose-100">
                These actions permanently delete data for ALL users and cannot be undone.
              </p>
            </div>
          </div>
          <div className="border-t border-rose-400/25 pt-4">
            <GlobalNukePanel onDeleted={refresh} />
          </div>
        </Card>
      </div>
    </div>
  )
}
