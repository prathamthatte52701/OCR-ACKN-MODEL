import { useEffect, useState } from 'react'
import api from '../utils/api'
import PaginationControls from '../components/PaginationControls'
import Banner from '../components/Banner'
import { formatIST } from '../utils/formatDate'

const PAGE_SIZE = 30

export default function AdminOrphanedFilesPage() {
  const [records, setRecords] = useState([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [busyId, setBusyId] = useState(null)

  async function load(pageToLoad = page) {
    setLoading(true)
    setError('')
    try {
      const res = await api.get('/admin/orphaned-files', { params: { page: pageToLoad, limit: PAGE_SIZE } })
      setRecords(res.data.orphanedFiles || [])
      setTotalPages(res.data.totalPages || 1)
      setTotal(res.data.totalOrphanedFiles || 0)
    } catch (err) {
      setError(err.userMessage || 'Could not load orphaned files.')
    } finally {
      setLoading(false)
    }
  }

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { load(page) }, [page])

  async function handleRetry(record) {
    setBusyId(record.id)
    setError('')
    setSuccess('')
    try {
      const res = await api.post(`/admin/orphaned-files/${record.id}/retry`)
      if (res.data.success) {
        setSuccess(res.data.message || 'File deleted successfully.')
        setRecords((prev) => prev.filter((r) => r.id !== record.id))
        setTotal((t) => Math.max(0, t - 1))
      } else {
        setError(res.data.message || 'Retry failed - this file still could not be deleted.')
        load(page)
      }
    } catch (err) {
      setError(err.userMessage || 'Could not retry this delete.')
    } finally {
      setBusyId(null)
    }
  }

  async function handleDismiss(record) {
    setBusyId(record.id)
    setError('')
    setSuccess('')
    try {
      await api.delete(`/admin/orphaned-files/${record.id}`)
      setSuccess('Record dismissed.')
      setRecords((prev) => prev.filter((r) => r.id !== record.id))
      setTotal((t) => Math.max(0, t - 1))
    } catch (err) {
      setError(err.userMessage || 'Could not dismiss this record.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <main className="mx-auto max-w-[1280px] px-4 py-8 sm:px-6 lg:px-10">
      <h1 className="mb-1 text-3xl font-black tracking-tight text-white">Orphaned Files</h1>
      <p className="mb-6 text-[14.7px] text-slate-500">
        {loading ? 'Loading...' : `${total} GridFS file${total !== 1 ? 's' : ''} that failed to delete and need review.`}
      </p>

      <Banner error={error} success={success} />

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-transparent border-t-emerald-400" />
        </div>
      ) : records.length === 0 ? (
        <div className="rounded-[24px] border border-emerald-300/12 bg-slate-900/60 px-4 py-10 text-center text-[13.6px] text-slate-500">
          Nothing here - every GridFS deletion has completed cleanly.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-[24px] border border-emerald-300/12 bg-slate-900/60">
          <table className="w-full text-left text-[13.6px]">
            <thead>
              <tr className="border-b border-white/8 text-[11.6px] font-black uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3">Failed</th>
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Context</th>
                <th className="px-4 py-3">Error</th>
                <th className="px-4 py-3">Attempts</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r) => (
                <tr key={r.id} className="border-b border-white/5 last:border-0">
                  <td className="px-4 py-3 whitespace-nowrap text-slate-400">{formatIST(r.updatedAt || r.createdAt)}</td>
                  <td className="px-4 py-3">
                    <div className="font-bold text-white">{r.owner?.username || 'unknown'}</div>
                    <div className="text-[11.6px] text-slate-500">{r.owner?.email}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded-full border border-amber-300/25 bg-amber-500/10 px-2.5 py-1 text-[11.6px] font-black uppercase text-amber-200">{r.context || 'unknown'}</span>
                  </td>
                  <td className="px-4 py-3 max-w-[320px] truncate text-rose-300" title={r.errorMessage}>
                    {r.errorType}: {r.errorMessage}
                  </td>
                  <td className="px-4 py-3 text-slate-400">{r.attemptCount}</td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <button
                        disabled={busyId === r.id}
                        onClick={() => handleRetry(r)}
                        className="rounded-full border border-emerald-300/25 bg-emerald-500/10 px-3 py-1.5 text-[11.6px] font-bold text-emerald-200 hover:border-emerald-300/45 disabled:opacity-50"
                      >
                        {busyId === r.id ? 'Working...' : 'Retry Delete'}
                      </button>
                      <button
                        disabled={busyId === r.id}
                        onClick={() => handleDismiss(r)}
                        className="rounded-full border border-white/10 bg-white/[0.035] px-3 py-1.5 text-[11.6px] font-bold text-slate-300 hover:border-rose-300/30 hover:bg-rose-500/10 disabled:opacity-50"
                      >
                        Dismiss
                      </button>
                    </div>
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
