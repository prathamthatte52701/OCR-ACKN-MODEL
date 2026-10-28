import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import api from '../utils/api'
import Banner from '../components/Banner'
import BackButton from '../components/BackButton'
import ConfirmModal from '../components/ConfirmModal'
import Modal from '../components/Modal'
import { Badge, Card, DataTable, EmptyState, ErrorState, PageHeader, Skeleton } from '../components/ui'
import { formatIST } from '../utils/formatDate'
import { notifyCountsChanged } from '../utils/events'
import UsersTabs from './users/UsersTabs'

// No 0/O/1/l/I. 12 chars with at least one upper, lower, digit and special.
const UPPER = 'ABCDEFGHJKLMNPQRSTUVWXYZ'
const LOWER = 'abcdefghijkmnpqrstuvwxyz'
const DIGIT = '23456789'
const SPECIAL = '!@#$%^&*?'
function generatePassword() {
  const rnd = (n) => {
    // rejection sampling: no modulo bias
    const max = Math.floor(0x100000000 / n) * n
    const a = new Uint32Array(1)
    do crypto.getRandomValues(a); while (a[0] >= max)
    return a[0] % n
  }
  const pick = (s) => s[rnd(s.length)]
  const all = UPPER + LOWER + DIGIT + SPECIAL
  const chars = [pick(UPPER), pick(LOWER), pick(DIGIT), pick(SPECIAL)]
  while (chars.length < 12) chars.push(pick(all))
  for (let i = chars.length - 1; i > 0; i--) {
    const j = rnd(i + 1)
    ;[chars[i], chars[j]] = [chars[j], chars[i]]
  }
  return chars.join('')
}

// The temporary password lives ONLY in this component's state, which unmounts with the dialog.
function TempPasswordModal({ request, onClose, onDone }) {
  const [password, setPassword] = useState('')
  const [shown, setShown] = useState(false)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    if (busy || !password) return
    setBusy(true)
    setError('')
    try {
      await api.post(`/admin/password-requests/${request.id}/temp-password`, { password })
      setPassword('')
      onDone(`Temporary password set for ${request.username}. Give it to them in person or by phone.`)
    } catch (err) {
      setError(err.userMessage || 'Could not set the password.')
      setBusy(false)
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(password)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setError('Could not copy. Select the password and copy it manually.')
    }
  }

  return (
    <Modal ariaLabel="Set temporary password" onClose={busy ? () => {} : onClose}>
      <form onSubmit={submit} autoComplete="off">
        <h2 className="mb-2 text-lg font-extrabold text-white">Set temp password</h2>
        <p className="mb-3 text-[14px] text-[var(--muted)]">
          For <strong className="text-white">{request.username}</strong> ({request.email}). They must change it at their next login.
        </p>
        <p className="mb-4 rounded-xl border border-amber-400/35 bg-amber-400/10 px-3.5 py-2.5 text-[13.5px] font-semibold text-amber-200">
          Check the person&apos;s identity in person or by phone before giving this password.
        </p>
        <label className="mb-1 block text-[13px] font-semibold text-[var(--muted)]" htmlFor="temp-pw">Temporary password</label>
        <input id="temp-pw" type={shown ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" spellCheck={false} maxLength={64} className="input" autoFocus />
        <div className="mt-2 flex flex-wrap gap-2">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShown((v) => !v)}>{shown ? 'Hide' : 'Show'}</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setPassword(generatePassword()); setShown(true); setCopied(false) }}>Generate</button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={!password} onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
        </div>
        <p className="mt-2 text-[12.5px] text-[var(--muted)]">8-64 characters with uppercase, lowercase, a number and a special character, no spaces.</p>
        {error && <div role="alert" className="mt-3 rounded-xl border border-rose-400/45 bg-rose-400/10 px-3.5 py-2.5 text-[14px] text-rose-200">{error}</div>}
        <div className="mt-5 flex flex-wrap gap-3">
          <button type="submit" className="btn btn-primary" disabled={busy || !password}>{busy ? 'Saving...' : 'Set password'}</button>
          <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>Cancel</button>
        </div>
      </form>
    </Modal>
  )
}

export default function PasswordRequestsPage() {
  const [requests, setRequests] = useState([])
  const [openCount, setOpenCount] = useState(0)
  const [pendingCount, setPendingCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [setting, setSetting] = useState(null)
  const [dismissing, setDismissing] = useState(null)
  const [busy, setBusy] = useState(false)

  const latestRequest = useRef(0)
  const load = useCallback(async () => {
    const requestId = ++latestRequest.current
    setLoading(true)
    setLoadError('')
    try {
      const res = await api.get('/admin/password-requests', { params: { status: showAll ? 'all' : 'open' } })
      if (requestId !== latestRequest.current) return
      setRequests(res.data.requests || [])
      setOpenCount(res.data.openCount || 0)
    } catch (err) {
      if (requestId !== latestRequest.current) return
      setLoadError(err.userMessage || 'Could not load password requests.')
    } finally {
      if (requestId === latestRequest.current) setLoading(false)
    }
  }, [showAll])

  // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
  useEffect(() => { load() }, [load])
  useEffect(() => {
    api.get('/admin/users', { params: { limit: 1, status: 'pending' } })
      .then((res) => setPendingCount(res.data.pendingCount || 0))
      .catch(() => {})
  }, [])

  function afterChange(message) {
    setSetting(null)
    setDismissing(null)
    setError('')
    setSuccess(message)
    notifyCountsChanged()
    load()
  }

  async function dismiss() {
    const r = dismissing
    setBusy(true)
    try {
      await api.post(`/admin/password-requests/${r.id}/dismiss`)
      afterChange(`Request from ${r.username} dismissed.`)
    } catch (err) {
      setDismissing(null)
      setSuccess('')
      setError(err.userMessage || 'Could not dismiss the request.')
      load()
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="mx-auto max-w-[1560px] px-4 py-6 sm:px-6 lg:px-8">
      <BackButton fallback="/" />
      <PageHeader title="Password requests" subtitle="Users who asked for a password reset" />
      <UsersTabs active="requests" pending={pendingCount} requests={openCount} />
      <Banner error={error} success={success} />

      <Card className="min-w-0 p-5" aria-label="Password requests">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[20px] font-bold text-white">{showAll ? 'All requests' : 'Open requests'}</h2>
          <label className="flex items-center gap-2 text-[14px] text-[var(--muted)]">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
            Show resolved too
          </label>
        </div>

        {loadError ? (
          <ErrorState message={loadError} onRetry={load} />
        ) : loading && requests.length === 0 ? (
          <div className="space-y-2" aria-busy="true">
            <Skeleton className="h-10 w-full" /><Skeleton className="h-10 w-full" /><Skeleton className="h-10 w-full" />
          </div>
        ) : requests.length === 0 ? (
          <EmptyState title={showAll ? 'No password requests yet' : 'No open password requests'} />
        ) : (
          <DataTable minWidth={820}>
            <thead>
              <tr>
                <th scope="col">User</th>
                <th scope="col">Email</th>
                <th scope="col">Note</th>
                <th scope="col">Requested</th>
                <th scope="col">Status</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {requests.map((r) => (
                <tr key={r.id}>
                  <td>{r.username}</td>
                  <td>{r.email}</td>
                  <td className="max-w-[280px] whitespace-pre-wrap break-words">{r.note || '-'}</td>
                  <td>{formatIST(r.updatedAt || r.createdAt)}</td>
                  <td><Badge tone={r.status === 'open' ? 'amber' : 'neutral'}>{r.status}</Badge></td>
                  <td>
                    {r.status === 'open' ? (
                      <div className="flex flex-wrap gap-2">
                        <button type="button" className="btn btn-primary btn-sm" onClick={() => { setSuccess(''); setSetting(r) }}>Set temp password</button>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDismissing(r)}>Dismiss</button>
                      </div>
                    ) : (
                      <span className="text-[13px] text-[var(--muted)]">{(r.resolution || '').replace(/_/g, ' ')}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Card>

      <AnimatePresence>
        {setting && <TempPasswordModal key={setting.id} request={setting} onClose={() => setSetting(null)} onDone={afterChange} />}
        {dismissing && (
          <ConfirmModal
            key={`d-${dismissing.id}`}
            title="Dismiss request?"
            message={`Dismiss the password request from ${dismissing.username}? Their password stays unchanged.`}
            confirmLabel="Yes, Dismiss"
            busy={busy}
            onConfirm={dismiss}
            onClose={() => setDismissing(null)}
          />
        )}
      </AnimatePresence>
    </main>
  )
}
