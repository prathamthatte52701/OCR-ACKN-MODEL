import { useEffect, useState } from 'react'
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { AnimatePresence } from 'framer-motion'
import api from '../utils/api'
import { useAdminAuth } from '../context/AdminAuthContext'
import Banner from '../components/Banner'
import ConfirmPurgeModal from '../components/ConfirmPurgeModal'

const STATUS_COLORS = { processed: '#34d399', failed: '#fb7185', uploaded: '#fbbf24' }
const TYPE_COLORS = ['#34d399', '#22d3ee']
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

function WarningIcon({ className = 'h-4 w-4' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  )
}

function purgeGlobalRange(body) {
  return api.delete('/admin/purge-range', { data: body }).then((res) => res.data)
}

function purgeGlobalMonths(body) {
  return api.delete('/admin/purge-months', { data: body }).then((res) => res.data)
}

// Two selectable modes, both ALWAYS applied across every user's data: (a)
// age-based oldest-first (1/2/3/6/9 months), (b) exact year + specific
// month(s). Distinct concepts offered side by side, not merged - reuses the
// same confirmation gate/rate limit/surgical row-removal mechanism as the
// per-user "Nuke This User" action on the user detail page.
function GlobalNukePanel() {
  const [mode, setMode] = useState('age')
  const [months, setMonths] = useState(6)
  const [year, setYear] = useState(new Date().getFullYear())
  const [selectedMonths, setSelectedMonths] = useState([])
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [banner, setBanner] = useState({ error: '', success: '' })

  function toggleMonth(monthNum) {
    setSelectedMonths((prev) =>
      prev.includes(monthNum) ? prev.filter((m) => m !== monthNum) : [...prev, monthNum].sort((a, b) => a - b)
    )
  }

  function handleDeleted(result) {
    setConfirmOpen(false)
    setBanner({ error: '', success: result?.message || 'Data deleted across all users.' })
  }

  const canOpenConfirm = mode === 'age' || selectedMonths.length > 0
  const monthLabel = selectedMonths.map((m) => MONTH_NAMES[m - 1]).join(', ')

  return (
    <section className="mt-6 rounded-[24px] border border-rose-500/25 bg-rose-950/10 p-6">
      <h2 className="mb-1 text-lg font-black text-rose-300">Global Nuke</h2>
      <p className="mb-4 text-[13.6px] text-rose-200/70">
        Permanently deletes matching documents (and their exported Excel rows) across EVERY
        user simultaneously. Not scoped to any one account.
      </p>

      <Banner error={banner.error} success={banner.success} />

      <div className="mb-3 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1.5 text-[12.6px] text-rose-200/80">
          <input type="radio" checked={mode === 'age'} onChange={() => setMode('age')} />
          Age-based (oldest first)
        </label>
        <label className="flex items-center gap-1.5 text-[12.6px] text-rose-200/80">
          <input type="radio" checked={mode === 'months'} onChange={() => setMode('months')} />
          Specific year + month(s)
        </label>
      </div>

      {mode === 'age' ? (
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-[12.6px] text-rose-200/80">Delete data older than</label>
          <select
            value={months}
            onChange={(e) => setMonths(Number(e.target.value))}
            className="rounded-lg border border-rose-800/50 bg-slate-950 px-2 py-1.5 text-[12.6px] text-white"
          >
            <option value={1}>1 month</option>
            <option value={2}>2 months</option>
            <option value={3}>3 months</option>
            <option value={6}>6 months</option>
            <option value={9}>9 months</option>
          </select>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-[12.6px] text-rose-200/80">Year</label>
            <input
              type="number"
              value={year}
              onChange={(e) => setYear(e.target.value)}
              className="w-24 rounded-lg border border-rose-800/50 bg-slate-950 px-2 py-1.5 text-[12.6px] text-white"
            />
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {MONTH_NAMES.map((name, idx) => {
              const monthNum = idx + 1
              const active = selectedMonths.includes(monthNum)
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => toggleMonth(monthNum)}
                  className={`rounded-lg border px-2.5 py-1.5 text-[11.6px] font-bold transition-colors ${active ? 'border-rose-500 bg-rose-700 text-white' : 'border-rose-800/50 bg-slate-950 text-rose-200/70 hover:bg-rose-900/30'}`}
                >
                  {name.slice(0, 3)}
                </button>
              )
            })}
          </div>
        </>
      )}

      <button
        type="button"
        onClick={() => setConfirmOpen(true)}
        disabled={!canOpenConfirm}
        className="mt-4 flex items-center gap-2 rounded-xl border-2 border-rose-500 bg-gradient-to-r from-rose-700 to-red-700 px-4 py-2 text-[12.6px] font-black text-white shadow-[0_0_0_3px_rgba(244,63,94,0.15)] transition-all hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <WarningIcon />
        Global Nuke
      </button>

      <AnimatePresence>
        {confirmOpen && mode === 'age' && (
          <ConfirmPurgeModal
            title="Confirm global age-based nuke"
            message={`This will permanently delete documents and exported Excel rows older than ${months} month(s), across EVERY user's account.`}
            phrase="NUKE ALL RANGE"
            purgeFn={(body) => purgeGlobalRange({ ...body, olderThanMonths: months })}
            onClose={() => setConfirmOpen(false)}
            onDeleted={handleDeleted}
          />
        )}
        {confirmOpen && mode === 'months' && (
          <ConfirmPurgeModal
            title="Confirm global year+month nuke"
            message={`This will permanently delete documents and exported Excel rows from ${monthLabel} ${year} only, across EVERY user's account. All other months and years are left completely untouched.`}
            phrase="NUKE ALL MONTHS"
            purgeFn={(body) => purgeGlobalMonths({ ...body, year: Number(year), months: selectedMonths })}
            onClose={() => setConfirmOpen(false)}
            onDeleted={handleDeleted}
          />
        )}
      </AnimatePresence>
    </section>
  )
}

function StatCard({ label, value, accent = 'text-white' }) {
  return (
    <div className="rounded-[22px] border border-emerald-300/12 bg-slate-900/60 p-5">
      <div className="text-[11.6px] font-black uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-black ${accent}`}>{value}</div>
    </div>
  )
}

function BreakdownRow({ label, value }) {
  return (
    <div className="flex items-center justify-between border-b border-white/5 py-2.5 last:border-0">
      <span className="text-[13.6px] text-slate-400">{label}</span>
      <span className="text-[13.6px] font-black text-white">{value}</span>
    </div>
  )
}

function ChartPanel({ title, children }) {
  return (
    <div className="rounded-[22px] border border-emerald-300/12 bg-slate-900/60 p-5">
      <h2 className="mb-3 text-[13.6px] font-black uppercase tracking-wide text-slate-500">{title}</h2>
      <div className="h-56">{children}</div>
    </div>
  )
}

const CHART_TOOLTIP_STYLE = {
  contentStyle: { background: '#0f172a', border: '1px solid rgba(16,185,129,0.2)', borderRadius: 10, fontSize: 12.6 },
  labelStyle: { color: '#e2e8f0' },
}

export default function AdminDashboardPage() {
  const { user } = useAdminAuth()
  const [telemetry, setTelemetry] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    api.get('/admin/telemetry')
      .then((res) => { if (!cancelled) setTelemetry(res.data) })
      .catch((err) => { if (!cancelled) setError(err.userMessage || 'Could not load telemetry.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const statusData = telemetry
    ? Object.entries(telemetry.documentsByStatus).map(([name, value]) => ({ name, value }))
    : []
  const typeData = telemetry
    ? Object.entries(telemetry.documentsByType).map(([name, value]) => ({ name, value }))
    : []

  return (
    <main className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6 lg:px-10">
      <h1 className="mb-1 text-3xl font-black tracking-tight text-white">Welcome, {user?.username}</h1>
      <p className="mb-6 text-[14.7px] text-slate-500">System-wide telemetry across every user.</p>

      <Banner error={error} />

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-transparent border-t-emerald-400" />
        </div>
      ) : telemetry && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Total users" value={telemetry.totalUsers} />
            <StatCard label="Total documents" value={telemetry.totalDocuments} />
            <StatCard label="Total exports" value={telemetry.totalExports} />
            <StatCard label="OCR failure rate" value={`${telemetry.ocrFailureRate}%`} accent={telemetry.ocrFailureRate > 10 ? 'text-rose-300' : 'text-emerald-300'} />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <ChartPanel title="Documents by status">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={statusData} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} paddingAngle={3}>
                    {statusData.map((entry) => (
                      <Cell key={entry.name} fill={STATUS_COLORS[entry.name] || '#64748b'} />
                    ))}
                  </Pie>
                  <Tooltip {...CHART_TOOLTIP_STYLE} />
                  <Legend wrapperStyle={{ fontSize: 12.6, color: '#94a3b8' }} />
                </PieChart>
              </ResponsiveContainer>
            </ChartPanel>

            <ChartPanel title="Documents by type">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={typeData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.12)" />
                  <XAxis dataKey="name" stroke="#64748b" fontSize={11.6} />
                  <YAxis stroke="#64748b" fontSize={11.6} allowDecimals={false} />
                  <Tooltip {...CHART_TOOLTIP_STYLE} />
                  <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                    {typeData.map((entry, i) => (
                      <Cell key={entry.name} fill={TYPE_COLORS[i % TYPE_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartPanel>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="rounded-[22px] border border-emerald-300/12 bg-slate-900/60 p-5">
              <h2 className="mb-3 text-[13.6px] font-black uppercase tracking-wide text-slate-500">Documents by status</h2>
              <BreakdownRow label="Processed" value={telemetry.documentsByStatus.processed} />
              <BreakdownRow label="Failed" value={telemetry.documentsByStatus.failed} />
              <BreakdownRow label="Uploaded" value={telemetry.documentsByStatus.uploaded} />
            </div>
            <div className="rounded-[22px] border border-emerald-300/12 bg-slate-900/60 p-5">
              <h2 className="mb-3 text-[13.6px] font-black uppercase tracking-wide text-slate-500">Recent activity</h2>
              <BreakdownRow label="Last 24 hours" value={telemetry.recentActivity.last24h} />
              <BreakdownRow label="Last 7 days" value={telemetry.recentActivity.last7d} />
            </div>
          </div>

          <GlobalNukePanel />
        </div>
      )}
    </main>
  )
}
