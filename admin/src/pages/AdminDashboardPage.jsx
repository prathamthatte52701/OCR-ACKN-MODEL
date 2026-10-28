import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../utils/api'
import { useAdminAuth } from '../context/AdminAuthContext'
import { useAutoRefresh } from '../hooks/useAutoRefresh'
import { notifyCountsChanged } from '../utils/events'
import { describeActivity, relativeTime } from '../utils/activity'
import { PALETTE } from '../utils/palette'
import Banner from '../components/Banner'
import { AreaChart, Donut, Gauge } from '../components/charts'
import { Avatar, Badge, Card, ChartCard, EmptyState, ErrorState, PageHeader, Skeleton, StatCard, Trend } from '../components/ui'

const TYPES = [
  { name: 'Tax Invoice', color: PALETTE.violet },
  { name: 'Delivery Challan', color: PALETTE.teal },
]

const isNum = (v) => typeof v === 'number' && Number.isFinite(v)
const lastN = (arr, n) => (Array.isArray(arr) && arr.length ? arr.slice(-n) : undefined)
const fmt = (n) => n.toLocaleString('en-US')

function Icon({ d }) {
  return (
    <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  )
}
const ICONS = {
  users: 'M17 20h5v-2a4 4 0 0 0-3-3.87M9 20H4v-2a4 4 0 0 1 3-3.87m10-6.13a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM7 9a3 3 0 1 1 6 0',
  check: 'M9 12l2 2 4-4m6 2a9 9 0 1 1-18 0 9 9 0 0 1 18 0z',
  doc: 'M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.59a1 1 0 0 1 .7.29l5.42 5.42a1 1 0 0 1 .29.7V19a2 2 0 0 1-2 2z',
  shield: 'M12 3l8 3v6c0 4.5-3.2 8.4-8 9-4.8-.6-8-4.5-8-9V6l8-3zm-3 9l2 2 4-4',
  wrench: 'M10.3 3.3a5 5 0 0 0 6.4 6.4l3.6 3.6a2 2 0 0 1-2.8 2.8l-3.6-3.6a5 5 0 0 1-6.4-6.4L9 8l2-2-.7-2.7z',
  chevron: 'M9 5l7 7-7 7',
}

function CardSkeleton({ h = 'h-40' }) {
  return <Skeleton className={`${h} w-full rounded-[18px]`} />
}

function category(action = '') {
  if (action === 'login' || action === 'signup') return { tone: 'blue', label: 'Account' }
  if (action.startsWith('user_')) return { tone: 'violet', label: 'Admin action' }
  if (action.startsWith('document_')) return { tone: 'teal', label: 'Documents' }
  return { tone: 'neutral', label: 'Other' }
}

function ActivityCard({ feed }) {
  return (
    <ChartCard title="Recent activity" className="h-full" action={<Link to="/logs" className="text-[14px] font-semibold text-[var(--violet-2)] no-underline hover:underline">View all</Link>}>
      {feed.length === 0 ? (
        <EmptyState title="Nothing has happened yet" hint="New sign-ins, approvals and uploads will show up here." />
      ) : (
        <ul className="divide-y divide-white/5">
          {feed.map((item) => {
            const cat = category(item.action)
            const name = item.user?.username
            return (
              <li key={item.id} className="flex items-center gap-3 py-3">
                <Avatar id={item.user?.id} name={name || '?'} size={36} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] font-semibold text-white" title={describeActivity(item)}>{describeActivity(item)}</p>
                  <time className="text-[13px] text-[var(--muted)]" dateTime={item.createdAt}>{relativeTime(item.createdAt)}</time>
                </div>
                <Badge tone={cat.tone}>{cat.label}</Badge>
              </li>
            )
          })}
        </ul>
      )}
    </ChartCard>
  )
}

function PendingCard({ pending, onApprove, busyId }) {
  const list = pending.oldest || []
  return (
    <ChartCard
      title={pending.count > 0 ? `Pending approvals (${pending.count})` : 'Pending approvals'}
      action={<Link to="/approvals" className="text-[14px] font-semibold text-[var(--violet-2)] no-underline hover:underline">Review</Link>}
    >
      {list.length === 0 ? (
        <EmptyState title="No pending requests" hint="New account requests will appear here." />
      ) : (
        <ul className="divide-y divide-white/5">
          {list.map((u) => (
            <li key={u.id} className="flex items-center gap-3 py-3">
              <Avatar id={u.id} name={u.username} size={36} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14px] font-semibold text-white" title={u.username}>{u.username}</p>
                <p className="truncate text-[13px] text-[var(--muted)]" title={u.email}>{u.email} · {relativeTime(u.createdAt) || 'recently'}</p>
              </div>
              <button type="button" className="btn btn-success btn-sm shrink-0" disabled={busyId === u.id} onClick={() => onApprove(u)} aria-label={`Approve ${u.username}`}>
                {busyId === u.id ? 'Approving...' : 'Approve'}
              </button>
            </li>
          ))}
        </ul>
      )}
    </ChartCard>
  )
}

function QuickAction({ to, icon, title, hint }) {
  return (
    <Link to={to} className="ui-card ui-card-flat flex items-center gap-4 p-4 no-underline transition-transform hover:-translate-y-0.5">
      <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-[var(--line)] bg-[rgba(124,108,255,0.14)] text-[var(--violet-2)]"><Icon d={icon} /></span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[15px] font-bold text-white">{title}</span>
        <span className="block truncate text-[13px] text-[var(--muted)]">{hint}</span>
      </span>
      <span className="text-[var(--muted)]"><Icon d={ICONS.chevron} /></span>
    </Link>
  )
}

function Dashboard({ data, onApprove, busyId }) {
  const byStatus = data.documentsByStatus
  const byType = data.documentsByType
  const series = data.series
  const processed = byStatus?.processed
  const failed = byStatus?.failed
  const finished = isNum(processed) && isNum(failed) ? processed + failed : 0
  const successRate = finished > 0 ? Math.round((processed / finished) * 1000) / 10 : null
  const pending = data.pendingUsers
  const proc = data.processedDocuments
  const feed = Array.isArray(data.activityFeed) ? data.activityFeed : []

  const days = Array.isArray(series?.days) ? series.days : []
  const docSeries = Array.isArray(series?.documents) ? series.documents : []
  const seriesTotal = docSeries.reduce((a, b) => a + b, 0)

  const typeSegs = byType ? TYPES.map((t) => ({ name: t.name, color: t.color, value: byType[t.name] || 0 })) : []
  const typeTotal = typeSegs.reduce((a, s) => a + s.value, 0)

  return (
    <div className="space-y-4">
      <section aria-label="Key numbers" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {isNum(data.totalUsers) && (
          <StatCard label="Total users" value={fmt(data.totalUsers)} tone="violet" icon={<Icon d={ICONS.users} />} to="/users"
            trend={data.trends?.users && <Trend current={data.trends.users.current} previous={data.trends.users.previous} suffix="vs previous 7 days" />}
            sparkline={lastN(series?.users, 14)} />
        )}
        {isNum(pending?.count) && (
          <StatCard label="Pending approvals" value={fmt(pending.count)} tone="blue" icon={<Icon d={ICONS.check} />} to="/approvals"
            trend={pending.count > 0 ? 'Waiting for review' : 'All caught up'} />
        )}
        {isNum(processed) && (
          <StatCard label="Documents processed" value={fmt(processed)} tone="teal" icon={<Icon d={ICONS.doc} />} to="/documents"
            trend={proc && <Trend current={proc.current} previous={proc.previous} suffix="vs previous 7 days" />}
            sparkline={lastN(series?.documents, 14)} />
        )}
        {isNum(processed) && isNum(failed) && (
          <StatCard label="OCR success rate" value={successRate === null ? '-' : `${successRate}%`} tone="amber" icon={<Icon d={ICONS.shield} />}
            trend={successRate === null ? 'No finished documents yet' : `${fmt(processed)} of ${fmt(finished)} finished documents`} />
        )}
      </section>

      <section aria-label="Charts" className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-[2fr_1fr_1fr]">
        {days.length > 1 && docSeries.length === days.length && (
          <ChartCard title="Documents over time" className="md:col-span-2 xl:col-span-1">
            <div className="mb-2 flex flex-wrap items-baseline gap-x-3 text-[14px]">
              <span className="text-[30px] font-extrabold leading-none text-white">{fmt(seriesTotal)}</span>
              <span className="text-[var(--muted)]">in the last {days.length} days</span>
              {data.trends?.documents && <span className="font-semibold text-[var(--teal)]"><Trend current={data.trends.documents.current} previous={data.trends.documents.previous} suffix="vs previous 7 days" /></span>}
            </div>
            <AreaChart days={days} values={docSeries} />
          </ChartCard>
        )}

        {byType && (
          <ChartCard title="Document types">
            {typeTotal === 0 ? (
              <EmptyState title="No documents yet" hint="Types appear once users upload documents." />
            ) : (
              <div className="flex flex-col items-center gap-4">
                <Donut segments={typeSegs} total={fmt(typeTotal)} size={160} />
                <ul className="w-full space-y-2">
                  {typeSegs.map((s) => (
                    <li key={s.name} className="flex items-center justify-between gap-3 text-[14px]">
                      <span className="flex min-w-0 items-center gap-2 text-[var(--text)]"><span className="h-3 w-3 shrink-0 rounded-full" style={{ background: s.color }} /><span className="truncate">{s.name}</span></span>
                      <span className="shrink-0 font-bold text-white">{fmt(s.value)} <span className="font-normal text-[var(--muted)]">({Math.round((s.value / typeTotal) * 100)}%)</span></span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </ChartCard>
        )}

        {isNum(processed) && isNum(failed) && (
          <ChartCard title="OCR success rate">
            {successRate === null ? (
              <EmptyState title="No finished documents yet" hint="The rate is shown once a document has been processed or has failed." />
            ) : (
              <div className="flex flex-col items-center">
                <Gauge value={successRate} label="Processed" />
                <p className="mt-2 text-center text-[13px] text-[var(--muted)]">{fmt(processed)} processed, {fmt(failed)} failed</p>
              </div>
            )}
          </ChartCard>
        )}
      </section>

      <section aria-label="Activity and shortcuts" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {Array.isArray(data.activityFeed) && <ActivityCard feed={feed} />}
        <div className="flex flex-col gap-4">
          {pending && <PendingCard pending={pending} onApprove={onApprove} busyId={busyId} />}
          <nav aria-label="Quick actions" className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <QuickAction to="/approvals" icon={ICONS.check} title="Approvals" hint={isNum(pending?.count) && pending.count > 0 ? `${pending.count} pending` : 'Review pending requests'} />
            <QuickAction to="/users" icon={ICONS.users} title="Users" hint="Manage user access" />
            <QuickAction to="/documents" icon={ICONS.doc} title="Documents" hint="Browse documents" />
            <QuickAction to="/maintenance" icon={ICONS.wrench} title="Maintenance" hint="Storage and cleanup" />
          </nav>
        </div>
      </section>
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading dashboard">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">{[0, 1, 2, 3].map((i) => <CardSkeleton key={i} h="h-40" />)}</div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-[2fr_1fr_1fr]">
        <CardSkeleton h="h-72" /><CardSkeleton h="h-72" /><CardSkeleton h="h-72" />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2"><CardSkeleton h="h-80" /><CardSkeleton h="h-80" /></div>
    </div>
  )
}

export default function AdminDashboardPage() {
  const { user } = useAdminAuth()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [notice, setNotice] = useState({ error: '', success: '' })
  const [busyId, setBusyId] = useState(null)
  const approving = useRef(new Set()) // synchronous guard: a double click is ignored, not re-sent

  const { markChanged, noteLoad } = useAutoRefresh({
    fetchData: () => api.get('/admin/telemetry').then((res) => res.data),
    applyData: (d) => { setData(d); setLoadError('') },
    busy: loading || busyId !== null,
    minIntervalMs: 55000, // beats are 15 s apart: 55 s keeps the period at 60 s despite timer drift
  })

  const load = useCallback(() => {
    noteLoad()
    return api.get('/admin/telemetry')
      .then((res) => { setData(res.data); setLoadError('') })
      .catch((err) => setLoadError(err.userMessage || 'Could not load the dashboard.'))
      .finally(() => setLoading(false))
  }, [noteLoad])

  const retry = () => { setLoading(true); load() }

  useEffect(() => {
    load()
  }, [load])

  async function approve(u) {
    if (approving.current.has(u.id)) return
    approving.current.add(u.id)
    markChanged()
    setBusyId(u.id)
    setNotice({ error: '', success: '' })
    try {
      await api.post(`/admin/users/${u.id}/approve`)
      setNotice({ error: '', success: `${u.username} approved.` })
    } catch (err) {
      setNotice({ error: err.userMessage || 'Could not approve this user.', success: '' })
    } finally {
      approving.current.delete(u.id)
      setBusyId(null)
      await load()
      notifyCountsChanged()
    }
  }

  const chips = []
  if (data?.failedDocuments > 0) chips.push(<Link key="f" to="/documents" className="no-underline"><Badge tone="red" dot>{fmt(data.failedDocuments)} failed {data.failedDocuments === 1 ? 'document' : 'documents'}</Badge></Link>)
  if (data?.orphanedFiles > 0) chips.push(<Link key="o" to="/orphaned-files" className="no-underline"><Badge tone="amber" dot>{fmt(data.orphanedFiles)} orphaned {data.orphanedFiles === 1 ? 'file' : 'files'}</Badge></Link>)

  return (
    <div className="mx-auto max-w-[1560px] px-4 py-6 sm:px-6 lg:px-8">
      <PageHeader
        title={`Welcome back, ${user?.username || 'admin'}`}
        subtitle="Here is what is happening with ACKN today"
        actions={chips.length > 0 ? chips : null}
      />
      <Banner error={notice.error} success={notice.success} />
      {loading ? <LoadingSkeleton /> : data ? <Dashboard data={data} onApprove={approve} busyId={busyId} /> : (
        <Card><ErrorState message={loadError || 'Could not load the dashboard.'} onRetry={retry} /></Card>
      )}
    </div>
  )
}
