import { useState } from 'react'
import { useAdminAuth } from '../context/AdminAuthContext'
import { validatePassword } from '../utils/validators'
import PasswordInput from '../components/PasswordInput'
import BackButton from '../components/BackButton'
import { Avatar, Badge, Card, PageHeader } from '../components/ui'

function Message({ error, success }) {
  if (!error && !success) return null
  return (
    <div role={error ? 'alert' : 'status'} className={`rounded-xl border px-3.5 py-2.5 text-[14px] ${error ? 'border-rose-400/40 bg-rose-400/10 text-rose-200' : 'border-emerald-400/35 bg-emerald-400/10 text-emerald-300'}`}>
      {error || success}
    </div>
  )
}

function DetailRow({ label, children }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl border border-[var(--line-soft)] bg-white/[0.03] px-4 py-3">
      <span className="shrink-0 text-[14px] text-[var(--muted)]">{label}</span>
      <span className="min-w-0 truncate text-[14px] font-semibold text-white">{children}</span>
    </div>
  )
}

function ProfileDetailsPanel({ user }) {
  return (
    <Card className="p-6">
      <h2 className="mb-5 text-xl font-extrabold tracking-tight text-white">Profile</h2>
      <div className="mb-5 flex justify-center">
        <Avatar id={user.id || user.email} name={user.username} size={72} />
      </div>
      <div className="space-y-3">
        <DetailRow label="Name"><span title={user.username}>{user.username}</span></DetailRow>
        <DetailRow label="Email"><span title={user.email}>{user.email}</span></DetailRow>
        <DetailRow label="Role"><Badge tone="violet" className="uppercase">{user.role}</Badge></DetailRow>
      </div>
    </Card>
  )
}

function ChangePasswordPanel({ changePassword }) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmNewPassword, setConfirmNewPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSuccess('')

    const err = validatePassword(newPassword)
    if (err) { setError(err); return }
    if (newPassword !== confirmNewPassword) { setError('New password and confirmation do not match.'); return }

    setSubmitting(true)
    try {
      await changePassword(currentPassword, newPassword, confirmNewPassword)
      setSuccess('Password changed. Your other sessions have been logged out.')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmNewPassword('')
    } catch (err) {
      setError(err.userMessage || 'Could not change your password. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card className="p-6">
      <h2 className="mb-5 text-xl font-extrabold tracking-tight text-white">Change password</h2>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="pw-current" className="ui-label mb-1 block">Current password</label>
          <PasswordInput id="pw-current" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} autoComplete="current-password" required />
        </div>
        <div>
          <label htmlFor="pw-new" className="ui-label mb-1 block">New password</label>
          <PasswordInput id="pw-new" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} minLength={8} maxLength={64} autoComplete="new-password" required />
          <p className="mt-1 text-[13px] text-[var(--muted)]">8-64 characters, with uppercase, lowercase, a number, and a special character - no spaces</p>
        </div>
        <div>
          <label htmlFor="pw-confirm" className="ui-label mb-1 block">Confirm new password</label>
          <PasswordInput id="pw-confirm" value={confirmNewPassword} onChange={(e) => setConfirmNewPassword(e.target.value)} autoComplete="new-password" required />
        </div>

        <Message error={error} success={success} />

        <button type="submit" disabled={submitting} className="btn btn-primary">
          {submitting ? 'Changing...' : 'Change password'}
        </button>
      </form>
    </Card>
  )
}

export default function AdminProfilePage() {
  const { user, changePassword } = useAdminAuth()
  if (!user) return null

  return (
    <div className="mx-auto max-w-[1000px] px-4 py-6 sm:px-6 lg:px-8">
      <BackButton fallback="/" />
      <PageHeader title="Account" />
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <ProfileDetailsPanel user={user} />
        <ChangePasswordPanel changePassword={changePassword} />
      </div>
    </div>
  )
}
