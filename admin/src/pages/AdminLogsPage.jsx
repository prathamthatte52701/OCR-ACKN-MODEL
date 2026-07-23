import { useEffect, useState } from 'react'
import api from '../utils/api'
import PaginationControls from '../components/PaginationControls'
import Banner from '../components/Banner'
import { formatIST } from '../utils/formatDate'

const PAGE_SIZE = 30
const ACTIONS = [
  'login',
  'signup',
  'password_change',
  'document_deleted',
  'document_exported',
  'document_corrected',
  'document_file_purged',
  'user_updated',
  'user_deleted',
]

export default function AdminLogsPage() {
  const [logs, setLogs] = useState([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [totalLogs, setTotalLogs] = useState(0)
  const [action, setAction] = useState('')
  const [userId, setUserId] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  async function load(pageToLoad = page) {
    setLoading(true)
    setError('')
    try {
      const params = { page: pageToLoad, limit: PAGE_SIZE }
      if (action) params.action = action
      if (userId.trim()) params.userId = userId.trim()
      const res = await api.get('/admin/logs', { params })
      setLogs(res.data.logs || [])
      setTotalPages(res.data.totalPages || 1)
      setTotalLogs(res.data.totalLogs || 0)
    } catch (err) {
      setError(err.userMessage || 'Could not load logs.')
    } finally {
      setLoading(false)
    }
  }

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { load(page) }, [page])

  function applyFilters(e) {
    e.preventDefault()
    setPage(1)
    load(1)
  }

  return (
    <main className="mx-auto max-w-[1280px] px-4 py-8 sm:px-6 lg:px-10">
      <h1 className="mb-1 text-3xl font-black tracking-tight text-white">Audit logs</h1>
      <p className="mb-6 text-[14.7px] text-slate-500">{loading ? 'Loading...' : `${totalLogs} entr${totalLogs !== 1 ? 'ies' : 'y'}`}</p>

      <form onSubmit={applyFilters} className="mb-5 flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1 block text-[12.6px] font-semibold text-slate-400">Action</label>
          <select value={action} onChange={(e) => setAction(e.target.value)} className="rounded-xl border border-white/10 bg-slate-950/60 px-3.5 py-2.5 text-[13.6px] text-white outline-none focus:border-emerald-300/60">
            <option value="">All actions</option>
            {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-[12.6px] font-semibold text-slate-400">User ID</label>
          <input value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="optional" className="rounded-xl border border-white/10 bg-slate-950/60 px-3.5 py-2.5 text-[13.6px] text-white outline-none focus:border-emerald-300/60" />
        </div>
        <button type="submit" className="rounded-xl bg-gradient-to-r from-emerald-600 to-teal-500 px-4 py-2.5 text-[13.6px] font-black text-white">
          Filter
        </button>
      </form>

      <Banner error={error} />

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-transparent border-t-emerald-400" />
        </div>
      ) : (
        <div className="overflow-x-auto rounded-[24px] border border-emerald-300/12 bg-slate-900/60">
          <table className="w-full text-left text-[13.6px]">
            <thead>
              <tr className="border-b border-white/8 text-[11.6px] font-black uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Action</th>
                <th className="px-4 py-3">Context</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id} className="border-b border-white/5 last:border-0">
                  <td className="px-4 py-3 whitespace-nowrap text-slate-400">{formatIST(l.createdAt)}</td>
                  <td className="px-4 py-3">
                    <div className="font-bold text-white">{l.user?.username || 'unknown'}</div>
                    <div className="text-[11.6px] text-slate-500">{l.user?.email}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded-full border border-emerald-300/25 bg-emerald-500/10 px-2.5 py-1 text-[11.6px] font-black uppercase text-emerald-200">{l.action}</span>
                  </td>
                  <td className="px-4 py-3 max-w-[360px] truncate text-slate-500" title={JSON.stringify(l.context)}>
                    {JSON.stringify(l.context)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <PaginationControls page={page} totalPages={totalPages} onChange={setPage} />
    </main>
  )
}
