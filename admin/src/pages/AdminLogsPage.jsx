import { useEffect, useState } from 'react'
import api from '../utils/api'
import PaginationControls from '../components/PaginationControls'
import { formatIST } from '../utils/formatDate'
import BackButton from '../components/BackButton'
import { Badge, Card, DataTable, EmptyState, ErrorState, PageHeader } from '../components/ui'
import { OwnerCell, TableSkeleton } from '../components/pageparts'

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
  'user_approved',
  'user_rejected',
  'user_email_changed',
  'admin_access',
  'chat_cleared',
  'chat_clear_blocked',
]

// Readable names for the chat audit actions. Their context holds counts and ids only, never message text.
const ACTION_LABELS = { chat_cleared: 'Chat cleared', chat_clear_blocked: 'Chat clear blocked' }

function actionTone(a = '') {
  if (/deleted|rejected|purged/.test(a)) return 'red'
  if (/approved/.test(a)) return 'green'
  if (a === 'login' || a === 'signup') return 'blue'
  if (a === 'admin_access' || a === 'password_change') return 'amber'
  return 'violet'
}

export default function AdminLogsPage() {
  const [logs, setLogs] = useState([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [totalLogs, setTotalLogs] = useState(0)
  const [action, setAction] = useState('')
  const [userId, setUserId] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  async function load(pageToLoad = page) {
    setLoading(true)
    setLoadError('')
    try {
      const params = { page: pageToLoad, limit: PAGE_SIZE }
      if (action) params.action = action
      if (userId.trim()) params.userId = userId.trim()
      const res = await api.get('/admin/logs', { params })
      setLogs(res.data.logs || [])
      setTotalPages(res.data.totalPages || 1)
      setTotalLogs(res.data.totalLogs || 0)
    } catch (err) {
      setLoadError(err.userMessage || 'Could not load logs.')
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
    <div className="mx-auto max-w-[1560px] px-4 py-6 sm:px-6 lg:px-8">
      <BackButton fallback="/" />
      <PageHeader
        title="Activity"
        subtitle={loading ? 'Loading...' : `${totalLogs} entr${totalLogs !== 1 ? 'ies' : 'y'}`}
      />

      <Card className="mb-5 p-4">
        <form onSubmit={applyFilters} className="flex flex-wrap items-end gap-3">
          <div className="min-w-[180px] flex-1 sm:flex-none">
            <label htmlFor="log-action" className="ui-label mb-1 block">Action</label>
            <select id="log-action" value={action} onChange={(e) => setAction(e.target.value)} className="input [color-scheme:dark] sm:w-56">
              <option value="">All actions</option>
              {ACTIONS.map((a) => <option key={a} value={a}>{ACTION_LABELS[a] ?? a}</option>)}
            </select>
          </div>
          <div className="min-w-[180px] flex-1 sm:flex-none">
            <label htmlFor="log-user" className="ui-label mb-1 block">User ID</label>
            <input id="log-user" value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="optional" className="input sm:w-64" />
          </div>
          <button type="submit" className="btn btn-primary">
            Filter
          </button>
        </form>
      </Card>

      <Card className="overflow-hidden">
        {loading ? (
          <TableSkeleton />
        ) : loadError ? (
          <ErrorState message={loadError} onRetry={() => load(page)} />
        ) : logs.length === 0 ? (
          <EmptyState title="No activity found" hint="Try a different action or user filter." />
        ) : (
          <DataTable minWidth={820}>
            <thead>
              <tr>
                <th>Time</th>
                <th>User</th>
                <th>Action</th>
                <th>Context</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id}>
                  <td className="whitespace-nowrap text-[var(--muted)]">{formatIST(l.createdAt)}</td>
                  <td><OwnerCell owner={l.user} /></td>
                  <td>
                    <Badge tone={actionTone(l.action)}>{ACTION_LABELS[l.action] ?? l.action}</Badge>
                  </td>
                  <td className="max-w-[360px] truncate text-[var(--muted)]" title={JSON.stringify(l.context)}>
                    {JSON.stringify(l.context)}
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
