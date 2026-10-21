import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import api from '../../utils/api'
import PaginationControls from '../../components/PaginationControls'
import Banner from '../../components/Banner'
import ConfirmModal from '../../components/ConfirmModal'
import RejectReasonModal from '../../components/RejectReasonModal'
import BackButton from '../../components/BackButton'
import { Avatar, Badge, Card, DataTable, EmptyState, ErrorState, PageHeader, StatCard } from '../../components/ui'
import { formatISTDate } from '../../utils/formatDate'
import { statusTone } from '../../utils/status'
import { notifyCountsChanged } from '../../utils/events'
import { useAdminAuth } from '../../context/AdminAuthContext'
import EditUserModal from './EditUserModal'
import RowMenu from './RowMenu'
import SelectedUserPanel from './SelectedUserPanel'
import SkeletonRows from './SkeletonRows'
import UsersTabs from './UsersTabs'

const ADMIN_LOCK_TIP = 'Admins can only be changed by themselves.'
const PAGE_SIZE = 30
const STATUSES = ['approved', 'pending', 'rejected']
const CHIPS = [
  { key: '', label: 'All' },
  { key: 'approved', label: 'Approved' },
  { key: 'pending', label: 'Pending' },
  { key: 'rejected', label: 'Rejected' },
]
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '')

const icon = (d) => (
  <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round">{d}</svg>
)
const ICONS = {
  total: icon(<><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14.5a6.5 6.5 0 0 1 3.5 5.5" /></>),
  approved: icon(<><circle cx="12" cy="12" r="9" /><path d="m8 12.5 3 3 5-6" /></>),
  pending: icon(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>),
  rejected: icon(<><circle cx="12" cy="12" r="9" /><path d="m9 9 6 6m0-6-6 6" /></>),
}

// Shared by /users (all filters) and /approvals (status fixed to pending).
export default function UsersView({ mode = 'users' }) {
  const approvals = mode === 'approvals'
  const { user: me } = useAdminAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const urlQ = searchParams.get('q') || ''
  const rawStatus = searchParams.get('status') || ''
  const rawRole = searchParams.get('role') || ''
  const status = approvals ? 'pending' : STATUSES.includes(rawStatus) ? rawStatus : ''
  const role = !approvals && (rawRole === 'user' || rawRole === 'admin') ? rawRole : ''

  const [users, setUsers] = useState([])
  const [totalPages, setTotalPages] = useState(1)
  const [totalUsers, setTotalUsers] = useState(0)
  const [pendingCount, setPendingCount] = useState(0)
  const [requestCount, setRequestCount] = useState(0)
  const [counts, setCounts] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [editingUser, setEditingUser] = useState(null)
  const [deletingUser, setDeletingUser] = useState(null)
  const [rejectingUser, setRejectingUser] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  // Only the newest request may update the table (overlapping loads from fast filter changes).
  const latestRequest = useRef(0)

  // Search box: local text, debounced into the URL `q` param; an external change of `q`
  // (the top-bar search) flows back into the box.
  const [qInput, setQInput] = useState(urlQ)
  const lastWritten = useRef(urlQ)

  const updateParams = useCallback((patch) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)))
      return next
    }, { replace: true })
  }, [setSearchParams])

  useEffect(() => {
    if (urlQ !== lastWritten.current) {
      lastWritten.current = urlQ
      setQInput(urlQ) // external URL change (top-bar search) -> update the box
    }
  }, [urlQ])

  useEffect(() => {
    const t = setTimeout(() => {
      const term = qInput.trim()
      if (term === lastWritten.current) return
      lastWritten.current = term
      updateParams({ q: term })
    }, 300)
    return () => clearTimeout(t)
  }, [qInput, updateParams])

  // Page resets to 1 whenever a filter changes (derived, no effect).
  const filterKey = `${status}|${urlQ}|${role}`
  const [pageState, setPageState] = useState({ key: filterKey, page: 1 })
  const page = pageState.key === filterKey ? pageState.page : 1
  const setPage = (p) => setPageState({ key: filterKey, page: p })

  const load = useCallback(async (pageToLoad = page) => {
    const requestId = ++latestRequest.current
    setLoading(true)
    setLoadError('')
    try {
      const params = { page: pageToLoad, limit: PAGE_SIZE }
      if (status) params.status = status
      if (urlQ) params.q = urlQ
      if (role) params.role = role
      const res = await api.get('/admin/users', { params })
      if (requestId !== latestRequest.current) return
      setUsers(res.data.users || [])
      setPendingCount(res.data.pendingCount || 0)
      setRequestCount(res.data.passwordRequestCount || 0)
      if (res.data.statusCounts) setCounts(res.data.statusCounts)
      setTotalPages(res.data.totalPages || 1)
      setTotalUsers(res.data.totalUsers || 0)
    } catch (err) {
      if (requestId !== latestRequest.current) return
      setLoadError(err.userMessage || 'Could not load users.')
    } finally {
      if (requestId === latestRequest.current) setLoading(false)
    }
  }, [page, status, urlQ, role])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load() }, [load])

  // Selected user: the list row is the source of truth; GET /admin/users/{id} adds
  // documentCount + lastActiveAt and is fetched only once a row is selected.
  const selected = users.find((u) => u.id === selectedId) || null
  const [detail, setDetail] = useState({ id: null, user: null })
  useEffect(() => {
    if (!selectedId) return undefined
    let off = false
    api.get(`/admin/users/${selectedId}`)
      .then((res) => { if (!off) setDetail({ id: selectedId, user: res.data.user }) })
      .catch(() => { if (!off) setDetail({ id: selectedId, user: null }) })
    return () => { off = true }
  }, [selectedId])
  const detailLoading = Boolean(selectedId) && detail.id !== selectedId

  const mergeUser = (updated) => setUsers((prev) => prev.map((u) => (u.id === updated.id ? { ...u, ...updated } : u)))

  async function toggleRole(user) {
    if (busyId) return
    const nextRole = user.role === 'admin' ? 'user' : 'admin'
    setBusyId(user.id)
    setError('')
    setSuccess('')
    try {
      const res = await api.patch(`/admin/users/${user.id}`, { role: nextRole })
      mergeUser(res.data.user)
      setSuccess(`${user.username} is now ${nextRole}.`)
    } catch (err) {
      setError(err.userMessage || 'Could not change role.')
    } finally {
      setBusyId(null)
    }
  }

  async function setStatus(user, action, reason = null) {
    if (busyId) return // double-click safe
    setBusyId(user.id)
    setError('')
    setSuccess('')
    try {
      await api.post(`/admin/users/${user.id}/${action}`, action === 'reject' ? { reason } : undefined)
      setSuccess(`${user.username} ${action === 'approve' ? 'approved' : 'rejected'}.`)
      setRejectingUser(null)
      notifyCountsChanged()
      load(page)
    } catch (err) {
      setError(err.userMessage || `Could not ${action} user.`)
      setRejectingUser(null)
    } finally {
      setBusyId(null)
    }
  }

  async function deleteUser(user) {
    if (busyId) return
    setBusyId(user.id)
    setError('')
    setSuccess('')
    try {
      await api.delete(`/admin/users/${user.id}`)
      setSuccess('User deleted.')
      setDeletingUser(null)
      if (selectedId === user.id) setSelectedId(null)
      notifyCountsChanged()
      load(page)
    } catch (err) {
      setError(err.userMessage || 'Could not delete user.')
      setDeletingUser(null)
    } finally {
      setBusyId(null)
    }
  }

  const stat = (key) => (counts ? counts[key] : '-')
  const hasFilters = Boolean(status || urlQ || role)
  const from = totalUsers === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = (page - 1) * PAGE_SIZE + users.length
  const firstLoad = loading && users.length === 0

  function rowActions(u) {
    const busy = busyId === u.id
    // another admin's row: the backend refuses these too (403) - this only greys them out
    const locked = u.role === 'admin' && u.id !== me?.id
    const tip = locked ? ADMIN_LOCK_TIP : undefined
    return (
      <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
        {u.status === 'pending' && (
          <>
            <button type="button" disabled={busy} onClick={() => setStatus(u, 'approve')} className="btn btn-success btn-sm">Approve</button>
            <button type="button" disabled={busy} onClick={() => setRejectingUser(u)} className="btn btn-danger btn-sm">Reject</button>
          </>
        )}
        {u.status === 'rejected' && (
          <button type="button" disabled={busy} onClick={() => setStatus(u, 'approve')} className="btn btn-success btn-sm">Re-approve</button>
        )}
        {u.status === 'approved' && u.role !== 'admin' && (
          <button type="button" disabled={busy} onClick={() => setRejectingUser(u)} className="btn btn-ghost btn-sm !text-amber-300">Revoke</button>
        )}
        <RowMenu
          label={`More actions for ${u.username}`}
          items={[
            { key: 'view', label: 'View activity', to: `/users/${u.id}` },
            { key: 'edit', label: 'Edit', disabled: locked, title: tip, onClick: () => setEditingUser(u) },
            { key: 'role', label: u.role === 'admin' ? 'Make user' : 'Make admin', disabled: busy || locked, title: tip, onClick: () => toggleRole(u) },
            { key: 'delete', label: 'Delete', danger: true, disabled: busy || locked, title: tip, onClick: () => setDeletingUser(u) },
          ]}
        />
      </div>
    )
  }

  return (
    <main className="mx-auto max-w-[1560px] px-4 py-6 sm:px-6 lg:px-8">
      <BackButton fallback="/" />
      <PageHeader
        title={approvals ? 'Approvals' : 'Users'}
        subtitle={approvals ? 'Review pending access requests' : 'Manage accounts and access permissions'}
      />

      <UsersTabs active={approvals ? 'approvals' : 'users'} pending={pendingCount} requests={requestCount} />

      {!approvals && (
        <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Total users" value={stat('total')} tone="violet" icon={ICONS.total} loading={!counts && loading} to="/users" />
          <StatCard label="Approved" value={stat('approved')} tone="teal" icon={ICONS.approved} loading={!counts && loading} to="/users?status=approved" />
          <StatCard label="Pending" value={stat('pending')} tone="amber" icon={ICONS.pending} loading={!counts && loading} to="/users?status=pending" />
          <StatCard label="Rejected" value={stat('rejected')} tone="pink" icon={ICONS.rejected} loading={!counts && loading} to="/users?status=rejected" />
        </div>
      )}

      <Banner error={error} success={success} />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="min-w-0 p-5" aria-label={approvals ? 'Pending requests' : 'User directory'}>
          <div className="mb-4 flex items-baseline gap-3">
            <h2 className="text-[20px] font-bold text-white">{approvals ? 'Pending requests' : 'User directory'}</h2>
            {!firstLoad && !loadError && <span className="text-[14px] text-[var(--muted)]">{totalUsers} user{totalUsers !== 1 ? 's' : ''}</span>}
          </div>

          <div className="mb-4 flex flex-wrap items-center gap-3">
            <div className="relative min-w-[200px] flex-1 sm:max-w-[320px]">
              <svg className="pointer-events-none absolute left-3.5 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-[var(--muted)]" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" strokeLinecap="round" /></svg>
              <input
                type="search"
                value={qInput}
                maxLength={100}
                onChange={(e) => setQInput(e.target.value)}
                placeholder="Search by name or email"
                aria-label="Search users by name or email"
                className="input pl-10"
              />
            </div>
            {!approvals && (
              <>
                <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-2">
                  {CHIPS.map((c) => (
                    <button
                      key={c.key || 'all'}
                      type="button"
                      aria-pressed={status === c.key}
                      onClick={() => { updateParams({ status: c.key }); setSuccess('') }}
                      className={`rounded-full border px-4 py-1.5 text-[14px] font-semibold transition-colors ${status === c.key ? 'border-violet-300/60 bg-violet-500 text-white shadow-[0_0_18px_rgba(124,92,255,0.45)]' : 'border-[var(--line)] bg-white/5 text-[var(--muted)] hover:text-white'}`}
                    >
                      {c.label}
                    </button>
                  ))}
                </div>
                <select
                  value={role}
                  onChange={(e) => updateParams({ role: e.target.value })}
                  aria-label="Filter by role"
                  className="input !w-auto"
                >
                  <option value="">All roles</option>
                  <option value="user">User</option>
                  <option value="admin">Admin</option>
                </select>
              </>
            )}
          </div>

          {!approvals && pendingCount > 0 && status !== 'pending' && (
            <button
              type="button"
              onClick={() => updateParams({ status: 'pending' })}
              className="mb-4 flex w-full items-center justify-between gap-3 rounded-2xl border border-amber-400/35 bg-amber-400/10 px-4 py-3 text-left text-[14px] font-semibold text-amber-200 hover:border-amber-300/60"
            >
              <span>{pendingCount} user{pendingCount !== 1 ? 's are' : ' is'} waiting for your approval</span>
              <span className="rounded-full bg-amber-400 px-3 py-1 text-[13px] font-bold text-slate-950">Review</span>
            </button>
          )}

          {loadError ? (
            <ErrorState message={loadError} onRetry={() => load(page)} />
          ) : !firstLoad && users.length === 0 ? (
            <EmptyState
              title={approvals ? 'No pending requests' : 'No users found'}
              hint={!approvals && hasFilters ? 'Try a different search or filter.' : undefined}
            />
          ) : (
            <div className={loading && !firstLoad ? 'opacity-60 transition-opacity' : undefined} aria-busy={loading}>
              <DataTable minWidth={880}>
                <thead>
                  <tr>
                    <th scope="col">User</th>
                    <th scope="col">Role</th>
                    <th scope="col">Joined</th>
                    <th scope="col">Documents</th>
                    <th scope="col">Status</th>
                    <th scope="col">Decision</th>
                    <th scope="col" className="text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {firstLoad ? <SkeletonRows cols={7} /> : users.map((u) => (
                    <tr key={u.id} aria-selected={u.id === selectedId} onClick={() => setSelectedId(u.id)} className="cursor-pointer">
                      <td className="max-w-[240px]">
                        <button type="button" onClick={() => setSelectedId(u.id)} className="flex w-full min-w-0 items-center gap-3 text-left" aria-label={`Select ${u.username}`}>
                          <Avatar id={u.id} name={u.username} size={40} />
                          <span className="min-w-0">
                            <span className="block truncate font-semibold text-white" title={u.username}>{u.username}</span>
                            <span className="block truncate text-[13px] text-[var(--muted)]" title={u.email}>{u.email}</span>
                          </span>
                        </button>
                      </td>
                      <td><Badge tone={u.role === 'admin' ? 'violet' : 'neutral'}>{cap(u.role)}</Badge></td>
                      <td className="whitespace-nowrap text-[var(--muted)]">{formatISTDate(u.createdAt)}</td>
                      <td className="text-white">{u.documentCount ?? '-'}</td>
                      <td><Badge tone={statusTone(u.status)} dot>{cap(u.status)}</Badge></td>
                      <td className="max-w-[200px] text-[var(--muted)]">
                        {u.decidedAt ? (
                          <>
                            <span className="capitalize">{u.decision}</span> {formatISTDate(u.decidedAt)}
                            {u.decisionReason && (
                              <div title={u.decisionReason} className="truncate text-[13px]">{u.decisionReason}</div>
                            )}
                          </>
                        ) : '-'}
                      </td>
                      <td>{rowActions(u)}</td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          )}

          {!loadError && users.length > 0 && (
            <p className="mt-4 text-[14px] text-[var(--muted)]">Showing {from}-{to} of {totalUsers} user{totalUsers !== 1 ? 's' : ''}</p>
          )}
          <PaginationControls page={page} totalPages={totalPages} onChange={setPage} />
        </Card>

        <div className={`${selected ? '' : 'hidden xl:block'} xl:sticky xl:top-20`}>
          <SelectedUserPanel
            user={selected}
            detail={detail.id === selectedId ? detail.user : null}
            detailLoading={detailLoading}
            busy={Boolean(busyId)}
            onApprove={(u) => setStatus(u, 'approve')}
            onReject={setRejectingUser}
          />
        </div>
      </div>

      <AnimatePresence>
        {editingUser && (
          <EditUserModal
            user={editingUser}
            onClose={() => setEditingUser(null)}
            onSaved={(updated, message) => {
              mergeUser(updated)
              setEditingUser(null)
              setSuccess(message)
            }}
          />
        )}
        {rejectingUser && (
          <RejectReasonModal
            user={rejectingUser}
            revoke={rejectingUser.status === 'approved'}
            busy={busyId === rejectingUser.id}
            onConfirm={(reason) => setStatus(rejectingUser, 'reject', reason)}
            onClose={() => setRejectingUser(null)}
          />
        )}
        {deletingUser && (
          <ConfirmModal
            title="Delete this user?"
            message={`Delete ${deletingUser.username} (${deletingUser.email})? This permanently removes their documents, workbooks, and exports. This cannot be undone.`}
            onConfirm={() => deleteUser(deletingUser)}
            onClose={() => setDeletingUser(null)}
            busy={busyId === deletingUser.id}
            strong
          />
        )}
      </AnimatePresence>
    </main>
  )
}
