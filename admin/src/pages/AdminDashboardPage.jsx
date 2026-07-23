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
import api from '../utils/api'
import { useAdminAuth } from '../context/AdminAuthContext'
import Banner from '../components/Banner'

const STATUS_COLORS = { processed: '#34d399', failed: '#fb7185', uploaded: '#fbbf24' }
const TYPE_COLORS = ['#34d399', '#22d3ee']

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
        </div>
      )}
    </main>
  )
}
