import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../utils/api'
import { useAdminAuth } from '../context/AdminAuthContext'
import { COUNTS_CHANGED_EVENT } from '../components/AdminLayout'
import Banner from '../components/Banner'
import { Donut, Gauge, Spinner } from '../components/hud'
import { HUD } from '../components/hudColors'
import { describeActivity, relativeTime } from '../utils/activity'

const STATUS_META = [
  { name: 'processed', label: 'Processed', color: HUD.green },
  { name: 'failed', label: 'Failed', color: HUD.red },
  { name: 'uploaded', label: 'Uploaded', color: HUD.amber },
]
const TYPE_META = [
  { name: 'Tax Invoice', color: HUD.cyan },
  { name: 'Delivery Challan', color: HUD.violet },
]

function Trend({ data }) {
  if (!data) return null
  const diff = data.current - data.previous
  const tone = diff > 0 ? 'text-[var(--hud-green)]' : 'text-[var(--hud-muted)]'
  const text = diff === 0 ? 'No change' : `${diff > 0 ? '+' : ''}${diff}`
  return (
    <p className={`mt-1 text-[13px] ${tone}`}>
      <span className="font-bold">{text}</span> vs previous 7 days <span className="text-[var(--hud-muted)]">({data.current} this week)</span>
    </p>
  )
}

function Kpi({ label, value, trend, color = HUD.green }) {
  return (
    <div className="hud-card hud-key p-5">
      <div className="hud-label">{label}</div>
      <div className="mt-2 text-4xl font-black" style={{ color, textShadow: `0 0 14px ${color}66` }}>{value}</div>
      <Trend data={trend} />
    </div>
  )
}

function AttentionCard({ to, label, value, tone = 'text-[var(--hud-text)]', hint }) {
  return (
    <Link to={to} className="hud-card block p-4 no-underline transition-colors hover:border-[var(--hud-green)]/50">
      <div className="hud-label">{label}</div>
      <div className={`mt-1 text-3xl font-black ${tone}`}>{value}</div>
      <div className="mt-1 text-[13px] text-[var(--hud-muted)]">{hint}</div>
    </Link>
  )
}

function PendingCard({ pending, onApprove, busyId }) {
  const list = pending?.oldest || []
  return (
    <section className="hud-card hud-key p-5" aria-labelledby="pending-h">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 id="pending-h" className="text-[16px] font-bold text-white">
          Pending approvals
          {pending?.count > 0 && <span className="ml-3 rounded-full bg-amber-400 px-2.5 py-0.5 text-[13px] font-black text-slate-950">{pending.count}</span>}
        </h2>
        {pending?.count > 0 && (
          <Link to="/users" className="text-[14px] font-semibold text-[var(--hud-cyan)] no-underline hover:underline">Review all</Link>
        )}
      </div>
      {list.length === 0 ? (
        <p className="py-6 text-center text-[14px] text-[var(--hud-muted)]">No pending requests</p>
      ) : (
        <ul className="divide-y divide-white/5">
          {list.map((u) => (
            <li key={u.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14px] font-bold text-white">{u.username}</p>
                <p className="truncate text-[13px] text-[var(--hud-muted)]">{u.email} · requested {relativeTime(u.createdAt) || 'recently'}</p>
              </div>
              <Link to="/users" className="rounded-full border border-white/10 px-3 py-1.5 text-[13px] font-bold text-[var(--hud-text)] no-underline hover:border-[var(--hud-cyan)]/50">Review</Link>
              <button
                type="button"
                disabled={busyId === u.id}
                onClick={() => onApprove(u)}
                className="rounded-full border border-[var(--hud-green)]/50 bg-[var(--hud-green)]/15 px-4 py-1.5 text-[13px] font-black text-[var(--hud-green)] shadow-[0_0_14px_rgba(43,255,136,0.18)] hover:bg-[var(--hud-green)]/25 disabled:opacity-50"
              >
                {busyId === u.id ? 'Approving...' : 'Approve'}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default function AdminDashboardPage() {
  const { user } = useAdminAuth()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [busyId, setBusyId] = useState(null)
  const approving = useRef(new Set()) // synchronous guard: a double click is ignored, not re-sent

  const load = useCallback(() => {
    return api.get('/admin/telemetry')
      .then((res) => { setData(res.data); setError('') })
      .catch((err) => setError(err.userMessage || 'Could not load the dashboard.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function approve(u) {
    if (approving.current.has(u.id)) return
    approving.current.add(u.id)
    setBusyId(u.id)
    setError('')
    setSuccess('')
    try {
      await api.post(`/admin/users/${u.id}/approve`)
      setSuccess(`${u.username} approved.`)
    } catch (err) {
      setError(err.userMessage || 'Could not approve this user.')
    } finally {
      approving.current.delete(u.id)
      setBusyId(null)
      await load()
      window.dispatchEvent(new Event(COUNTS_CHANGED_EVENT))
    }
  }

  const byStatus = data?.documentsByStatus || {}
  const byType = data?.documentsByType || {}
  const finished = (byStatus.processed || 0) + (byStatus.failed || 0)
  const successRate = finished > 0 ? Math.round(((byStatus.processed || 0) / finished) * 1000) / 10 : null
  const typeMax = Math.max(1, ...TYPE_META.map((t) => byType[t.name] || 0))
  const feed = data?.activityFeed || []

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6 lg:px-10">
      <h1 className="text-3xl font-black tracking-tight text-white">Welcome, {user?.username}</h1>
      <p className="mb-6 mt-1 text-[14px] text-[var(--hud-muted)]">Overview of all users and documents</p>

      <Banner error={error} success={success} />

      {loading ? <Spinner /> : data && (
        <div className="space-y-6">
          <section aria-label="Needs attention" className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2"><PendingCard pending={data.pendingUsers} onApprove={approve} busyId={busyId} /></div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 lg:grid-cols-1">
              <AttentionCard to="/documents" label="Failed documents" value={data.failedDocuments} tone={data.failedDocuments > 0 ? 'text-[var(--hud-red)]' : 'text-[var(--hud-text)]'} hint="Open documents" />
              <AttentionCard to="/orphaned-files" label="Orphaned files" value={data.orphanedFiles} tone={data.orphanedFiles > 0 ? 'text-[var(--hud-amber)]' : 'text-[var(--hud-text)]'} hint="Files without a record" />
              <AttentionCard to="/documents" label="OCR failure rate" value={`${data.ocrFailureRate}%`} tone={data.ocrFailureRate > 10 ? 'text-[var(--hud-red)]' : 'text-[var(--hud-green)]'} hint="Of finished documents" />
            </div>
          </section>

          <section aria-label="Totals" className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Kpi label="Total users" value={data.totalUsers} trend={data.trends?.users} color={HUD.cyan} />
            <Kpi label="Total documents" value={data.totalDocuments} trend={data.trends?.documents} />
            <Kpi label="Total exports" value={data.totalExports} trend={data.trends?.exports} color={HUD.violet} />
          </section>

          <section aria-label="Charts" className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="hud-card p-5">
              <h2 className="hud-label mb-3">Documents by status</h2>
              <div className="flex flex-col items-center gap-4 sm:flex-row lg:flex-col xl:flex-row">
                <Donut segments={STATUS_META.map((s) => ({ ...s, value: byStatus[s.name] || 0 }))} total={data.totalDocuments} />
                <ul className="w-full space-y-2">
                  {STATUS_META.map((s) => (
                    <li key={s.name} className="flex items-center justify-between gap-3 text-[14px]">
                      <span className="flex items-center gap-2 text-[var(--hud-muted)]"><span className="h-3 w-3 rounded-sm" style={{ background: s.color }} />{s.label}</span>
                      <span className="font-black text-white">{byStatus[s.name] || 0}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="hud-card p-5">
              <h2 className="hud-label mb-4">Documents by type</h2>
              <ul className="space-y-5">
                {TYPE_META.map((t) => {
                  const v = byType[t.name] || 0
                  return (
                    <li key={t.name}>
                      <div className="mb-1 flex items-baseline justify-between text-[14px]">
                        <span className="text-[var(--hud-text)]">{t.name}</span>
                        <span className="font-black text-white">{v}</span>
                      </div>
                      <div className="h-3 overflow-hidden rounded-full bg-white/5" role="presentation">
                        <div className="h-full rounded-full" style={{ width: `${(v / typeMax) * 100}%`, background: t.color, boxShadow: `0 0 10px ${t.color}66` }} />
                      </div>
                    </li>
                  )
                })}
              </ul>
            </div>

            <div className="hud-card flex flex-col items-center justify-center p-5">
              <h2 className="hud-label mb-3 self-start">OCR success rate</h2>
              {successRate === null ? (
                <p className="py-10 text-center text-[14px] text-[var(--hud-muted)]">No finished documents yet</p>
              ) : (
                <Gauge value={successRate} label="success" color={successRate >= 90 ? HUD.green : successRate >= 70 ? HUD.amber : HUD.red} caption={`${byStatus.processed || 0} of ${finished} finished documents`} />
              )}
            </div>
          </section>

          <section className="hud-card p-5" aria-labelledby="feed-h">
            <div className="mb-3 flex items-center justify-between">
              <h2 id="feed-h" className="text-[16px] font-bold text-white">Recent activity</h2>
              <Link to="/logs" className="text-[14px] font-semibold text-[var(--hud-cyan)] no-underline hover:underline">View all</Link>
            </div>
            {feed.length === 0 ? (
              <p className="py-6 text-center text-[14px] text-[var(--hud-muted)]">Nothing has happened yet</p>
            ) : (
              <ul className="divide-y divide-white/5">
                {feed.map((item) => (
                  <li key={item.id} className="flex items-baseline justify-between gap-4 py-2.5">
                    <span className="min-w-0 text-[14px] text-[var(--hud-text)]">{describeActivity(item)}</span>
                    <time className="shrink-0 text-[13px] text-[var(--hud-muted)]" dateTime={item.createdAt}>{relativeTime(item.createdAt)}</time>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
