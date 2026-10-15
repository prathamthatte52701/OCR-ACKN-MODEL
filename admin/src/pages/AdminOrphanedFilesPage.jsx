import { useEffect, useState } from 'react'
import api from '../utils/api'
import PaginationControls from '../components/PaginationControls'
import Banner from '../components/Banner'
import { formatIST } from '../utils/formatDate'
import BackButton from '../components/BackButton'
import { Badge, Card, DataTable, EmptyState, ErrorState, PageHeader } from '../components/ui'
import { OwnerCell, TableSkeleton } from '../components/pageparts'
import { notifyCountsChanged } from '../utils/events'

const PAGE_SIZE = 30

export default function AdminOrphanedFilesPage() {
  const [records, setRecords] = useState([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [success, setSuccess] = useState('')
  const [busyId, setBusyId] = useState(null)

  async function load(pageToLoad = page) {
    setLoading(true)
    setLoadError('')
    try {
      const res = await api.get('/admin/orphaned-files', { params: { page: pageToLoad, limit: PAGE_SIZE } })
      setRecords(res.data.orphanedFiles || [])
      setTotalPages(res.data.totalPages || 1)
      setTotal(res.data.totalOrphanedFiles || 0)
    } catch (err) {
      setLoadError(err.userMessage || 'Could not load orphaned files.')
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
        notifyCountsChanged()
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
      notifyCountsChanged()
    } catch (err) {
      setError(err.userMessage || 'Could not dismiss this record.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="mx-auto max-w-[1560px] px-4 py-6 sm:px-6 lg:px-8">
      <BackButton fallback="/" />
      <PageHeader
        title="Orphaned files"
        subtitle={loading ? 'Loading...' : `${total} GridFS file${total !== 1 ? 's' : ''} that failed to delete and need review.`}
      />

      <Banner error={error} success={success} />

      <Card className="overflow-hidden">
        {loading ? (
          <TableSkeleton />
        ) : loadError ? (
          <ErrorState message={loadError} onRetry={() => load(page)} />
        ) : records.length === 0 ? (
          <EmptyState title="Nothing here" hint="Every GridFS deletion has completed cleanly." />
        ) : (
          <DataTable minWidth={960}>
            <thead>
              <tr>
                <th>Failed</th>
                <th>User</th>
                <th>Context</th>
                <th>Error</th>
                <th>Attempts</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r) => (
                <tr key={r.id}>
                  <td className="whitespace-nowrap text-[var(--muted)]">{formatIST(r.updatedAt || r.createdAt)}</td>
                  <td><OwnerCell owner={r.owner} /></td>
                  <td>
                    <Badge tone="amber">{r.context || 'unknown'}</Badge>
                  </td>
                  <td className="max-w-[320px] truncate text-[var(--red)]" title={r.errorMessage}>
                    {r.errorType}: {r.errorMessage}
                  </td>
                  <td className="text-[var(--muted)]">{r.attemptCount}</td>
                  <td>
                    <div className="flex flex-wrap justify-end gap-2">
                      <button
                        disabled={busyId === r.id}
                        onClick={() => handleRetry(r)}
                        className="btn btn-success btn-sm"
                      >
                        {busyId === r.id ? 'Working...' : 'Retry Delete'}
                      </button>
                      <button
                        disabled={busyId === r.id}
                        onClick={() => handleDismiss(r)}
                        className="btn btn-ghost btn-sm"
                      >
                        Dismiss
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Card>

      <PaginationControls page={page} totalPages={totalPages} onChange={setPage} />
    </div>
  )
}
