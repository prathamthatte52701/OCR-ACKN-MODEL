import { useAdminAuth } from '../context/AdminAuthContext'
import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import api from '../utils/api'
import PaginationControls from '../components/PaginationControls'
import Banner from '../components/Banner'
import ConfirmPurgeModal from '../components/ConfirmPurgeModal'
import { formatIST, formatISTDate } from '../utils/formatDate'
import { statusTone } from '../utils/status'
import BackButton from '../components/BackButton'
import { Avatar, Badge, Card, DataTable, EmptyState, ErrorState, Skeleton, StatCard } from '../components/ui'
import SkeletonRows from './users/SkeletonRows'

const SECTION_PAGE_SIZE = 10
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '')

function WarningIcon({ className = 'h-4 w-4' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  )
}

// Two selectable modes, both ALWAYS scoped strictly to this one user's data
// (documents, GridFS files, workbook rows/exports tied to them): (a)
// age-based oldest-first (1/2/3/6/9 months), (b) exact year + specific
// month(s). Mirrors the Dashboard's Global Nuke panel exactly - only the
// target scope (this user vs every user) differs.
function NukeUserPanel({ userId, username }) {
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
    setBanner({ error: '', success: result?.message || 'Data deleted for this user.' })
  }

  const canOpenConfirm = mode === 'age' || selectedMonths.length > 0
  const monthLabel = selectedMonths.map((m) => MONTH_NAMES[m - 1]).join(', ')

  return (
    <Card variant="danger" className="mb-8 p-6" aria-label="Nuke this user">
      <h2 className="mb-1 text-lg font-bold text-rose-300">Nuke This User</h2>
      <p className="mb-4 text-[14px] text-rose-100/80">
        Permanently deletes this user&apos;s documents (and their exported Excel rows), scoped
        strictly to {username || 'this user'} - every other user&apos;s data is untouched.
      </p>

      <Banner error={banner.error} success={banner.success} />

      <div className="mb-3 flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-[14px] text-rose-100">
          <input type="radio" checked={mode === 'age'} onChange={() => setMode('age')} />
          Age-based (oldest first)
        </label>
        <label className="flex items-center gap-2 text-[14px] text-rose-100">
          <input type="radio" checked={mode === 'months'} onChange={() => setMode('months')} />
          Specific year + month(s)
        </label>
      </div>

      {mode === 'age' ? (
        <div className="flex flex-wrap items-center gap-3">
          <label htmlFor="nuke-older-than" className="text-[14px] text-rose-100">Delete data older than</label>
          <select
            id="nuke-older-than"
            value={months}
            onChange={(e) => setMonths(Number(e.target.value))}
            className="input !w-auto"
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
            <label htmlFor="nuke-year" className="text-[14px] text-rose-100">Year</label>
            <input
              id="nuke-year"
              type="number"
              value={year}
              onChange={(e) => setYear(e.target.value)}
              className="input !w-28"
            />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {MONTH_NAMES.map((name, idx) => {
              const monthNum = idx + 1
              const active = selectedMonths.includes(monthNum)
              return (
                <button
                  key={name}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleMonth(monthNum)}
                  className={`btn btn-sm ${active ? '!border-rose-300 !bg-rose-600 !text-white' : 'btn-ghost'}`}
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
        className="btn mt-4 !border-rose-300 !bg-rose-600 !text-white hover:!bg-rose-500"
      >
        <WarningIcon />
        Nuke This User
      </button>

      <AnimatePresence>
        {confirmOpen && mode === 'age' && (
          <ConfirmPurgeModal
            title="Confirm user-scoped nuke"
            message={`This will permanently delete ALL of ${username || 'this user'}'s documents and exported Excel rows older than ${months} month(s). No other user's data is affected.`}
            phrase="NUKE USER"
            purgeFn={(body) => api.delete(`/admin/users/${userId}/purge-range`, { data: { ...body, olderThanMonths: months } }).then((res) => res.data)}
            onClose={() => setConfirmOpen(false)}
            onDeleted={handleDeleted}
          />
        )}
        {confirmOpen && mode === 'months' && (
          <ConfirmPurgeModal
            title="Confirm user-scoped year+month nuke"
            message={`This will permanently delete ${username || 'this user'}'s documents and exported Excel rows from ${monthLabel} ${year} only. All other months/years and every other user's data are left completely untouched.`}
            phrase="NUKE USER MONTHS"
            purgeFn={(body) => api.delete(`/admin/users/${userId}/purge-months`, { data: { ...body, year: Number(year), months: selectedMonths } }).then((res) => res.data)}
            onClose={() => setConfirmOpen(false)}
            onDeleted={handleDeleted}
          />
        )}
      </AnimatePresence>
    </Card>
  )
}

function docNumber(doc) {
  if (doc.documentType === 'Tax Invoice') return [doc.taxInvoiceNo, doc.referenceNo].filter(Boolean).join(' / ') || '-'
  return doc.number || '-'
}

function exportNumber(row) {
  if (row.documentType === 'Tax Invoice') return [row.taxInvoiceNo, row.referenceNo].filter(Boolean).join(' / ') || '-'
  return row.number || '-'
}

// One paginated list of a user's records (documents / exports / logs). Fetch state is keyed
// so a page/user change shows skeleton rows until the matching response lands, and a
// failure shows a retry instead of silently leaving the table empty.
function useUserSection(path, userId, page) {
  const [nonce, setNonce] = useState(0)
  const key = `${userId}|${page}|${nonce}`
  const [res, setRes] = useState({ key: '', data: null, error: '' })
  useEffect(() => {
    let off = false
    api.get(path, { params: { userId, page, limit: SECTION_PAGE_SIZE } })
      .then((r) => { if (!off) setRes({ key, data: r.data, error: '' }) })
      .catch((err) => { if (!off) setRes({ key, data: null, error: err.userMessage || 'Could not load this section.' }) })
    return () => { off = true }
  }, [path, userId, page, key])
  const retry = useCallback(() => setNonce((n) => n + 1), [])
  return { data: res.data, error: res.key === key ? res.error : '', loading: res.key !== key, retry }
}

function Section({ title, count, state, page, onPageChange, cols, emptyTitle, head, children }) {
  return (
    <section className="mb-8" aria-label={title}>
      <Card className="p-5">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 className="text-[18px] font-bold text-white">{title}</h2>
          <span className="text-[14px] text-[var(--muted)]">{count} total</span>
        </div>
        {state.error ? (
          <ErrorState message={state.error} onRetry={state.retry} />
        ) : !state.loading && children.length === 0 ? (
          <EmptyState title={emptyTitle} />
        ) : (
          <DataTable minWidth={620}>
            <thead><tr>{head}</tr></thead>
            <tbody>{state.loading ? <SkeletonRows cols={cols} /> : children}</tbody>
          </DataTable>
        )}
      </Card>
      <PaginationControls page={page} totalPages={state.data?.totalPages || 1} onChange={onPageChange} />
    </section>
  )
}

export default function AdminUserDetailPage() {
  const { id } = useParams()
  const [user, setUser] = useState(null)
  const { user: me } = useAdminAuth()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reloadNonce, setReloadNonce] = useState(0)

  const [docPage, setDocPage] = useState(1)
  const [expPage, setExpPage] = useState(1)
  const [logPage, setLogPage] = useState(1)
  const docs = useUserSection('/admin/documents', id, docPage)
  const exps = useUserSection('/admin/exports', id, expPage)
  const logs = useUserSection('/admin/logs', id, logPage)
  const docTotal = docs.data?.totalDocuments || 0
  const expTotal = exps.data?.totalExports || 0
  const logTotal = logs.data?.totalLogs || 0

  useEffect(() => {
    let off = false
    // eslint-disable-next-line react-hooks/set-state-in-effect -- standard fetch-on-mount pattern
    setLoading(true)
    setError('')
    api.get(`/admin/users/${id}`)
      .then((res) => { if (!off) setUser(res.data.user) })
      .catch((err) => { if (!off) setError(err.userMessage || 'Could not load user.') })
      .finally(() => { if (!off) setLoading(false) })
    return () => { off = true }
  }, [id, reloadNonce])

  const statusIcon = (
    <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="m8 12.5 3 3 5-6" /></svg>
  )
  const docIcon = (
    <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /></svg>
  )
  const calIcon = (
    <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round"><rect x="3.5" y="5" width="17" height="15" rx="2" /><path d="M3.5 10h17M8 3v4M16 3v4" /></svg>
  )

  return (
    <main className="mx-auto max-w-[1560px] px-4 py-6 sm:px-6 lg:px-8">
      <BackButton fallback="/users" />

      {loading ? (
        <Card className="mb-6 p-6" aria-busy="true">
          <div className="flex items-center gap-4">
            <Skeleton className="h-16 w-16 !rounded-full" />
            <div className="space-y-2"><Skeleton className="h-7 w-48" /><Skeleton className="h-5 w-64" /></div>
          </div>
        </Card>
      ) : error ? (
        <Card className="mb-6"><ErrorState message={error} onRetry={() => setReloadNonce((n) => n + 1)} /></Card>
      ) : user && (
        <>
          <Card className="mb-6 flex flex-wrap items-center justify-between gap-4 p-6">
            <div className="flex min-w-0 items-center gap-4">
              <Avatar id={user.id} name={user.username} size={64} />
              <div className="min-w-0">
                <h1 className="truncate text-[28px] font-extrabold leading-tight tracking-tight text-white" title={user.username}>{user.username}</h1>
                <p className="truncate text-[15px] text-[var(--violet-2)]" title={user.email}>{user.email}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Badge tone={user.role === 'admin' ? 'violet' : 'neutral'}>{cap(user.role)}</Badge>
              <Badge tone={statusTone(user.status)} dot>{cap(user.status)}</Badge>
            </div>
          </Card>

          <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard label="Documents" value={user.documentCount ?? docTotal} tone="violet" icon={docIcon} />
            <StatCard label="Joined" value={<span className="text-[24px]">{formatISTDate(user.createdAt)}</span>} tone="blue" icon={calIcon} />
            <StatCard label="Status" value={<span className="text-[24px]">{cap(user.status)}</span>} tone={user.status === 'approved' ? 'teal' : user.status === 'pending' ? 'amber' : 'pink'} icon={statusIcon} />
          </div>

          {user.role === 'admin' && user.id !== me?.id ? (
            <p className="ui-card ui-card-flat mb-6 px-4 py-3 text-[14px] text-[var(--muted)]">
              Admins can only be changed by themselves.
            </p>
          ) : (
            <NukeUserPanel userId={id} username={user.username} />
          )}
        </>
      )}

      <Section
        title="Documents" count={docTotal} state={docs} page={docPage} onPageChange={setDocPage} cols={5} emptyTitle="No documents."
        head={<><th>Type</th><th>Number</th><th>Date</th><th>Status</th><th>Uploaded</th></>}
      >
        {(docs.data?.documents || []).map((d) => (
          <tr key={d._id}>
            <td>{d.documentType}</td>
            <td>{docNumber(d)}</td>
            <td className="text-[var(--muted)]">{d.date || '-'}</td>
            <td><Badge tone={statusTone(d.uploadStatus)}>{cap(d.uploadStatus)}</Badge></td>
            <td className="whitespace-nowrap text-[var(--muted)]">{formatIST(d.createdAt)}</td>
          </tr>
        ))}
      </Section>

      <Section
        title="Export Activity" count={expTotal} state={exps} page={expPage} onPageChange={setExpPage} cols={5} emptyTitle="No exports."
        head={<><th>Type</th><th>Number</th><th>Date</th><th>Exported At</th><th>Workbook</th></>}
      >
        {(exps.data?.exports || []).map((row) => (
          <tr key={row.id}>
            <td>{row.documentType}</td>
            <td>{exportNumber(row)}</td>
            <td className="text-[var(--muted)]">{row.date || '-'}</td>
            <td className="whitespace-nowrap text-[var(--muted)]">{formatIST(row.exportedAt)}</td>
            <td className="max-w-[220px] truncate" title={row.workbook?.filename}>{row.workbook?.filename || <span className="text-[var(--muted)]">Unknown</span>}</td>
          </tr>
        ))}
      </Section>

      <Section
        title="Activity Log" count={logTotal} state={logs} page={logPage} onPageChange={setLogPage} cols={3} emptyTitle="No log entries."
        head={<><th>Time</th><th>Action</th><th>Context</th></>}
      >
        {(logs.data?.logs || []).map((l) => (
          <tr key={l.id}>
            <td className="whitespace-nowrap text-[var(--muted)]">{formatIST(l.createdAt)}</td>
            <td><Badge tone="violet">{l.action}</Badge></td>
            <td className="max-w-[360px] truncate text-[var(--muted)]" title={JSON.stringify(l.context)}>
              {JSON.stringify(l.context)}
            </td>
          </tr>
        ))}
      </Section>
    </main>
  )
}
