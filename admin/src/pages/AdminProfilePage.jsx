import { useState } from 'react'
import { useAdminAuth } from '../context/AdminAuthContext'
import { validatePassword } from '../utils/validators'
import PasswordInput from '../components/PasswordInput'

const labelClass = 'mb-1 block text-[12.6px] font-semibold text-slate-400'
const panelClass = 'rounded-[28px] border border-emerald-300/12 bg-slate-900/68 p-6 shadow-2xl shadow-slate-950/30 backdrop-blur-xl'

function Message({ error, success }) {
  if (!error && !success) return null
  return (
    <div className={`rounded-xl border px-3.5 py-2.5 text-[13.6px] ${error ? 'border-rose-400/25 bg-rose-500/10 text-rose-200' : 'border-emerald-400/25 bg-emerald-500/10 text-emerald-200'}`}>
      {error || success}
    </div>
  )
}

function ProfileDetailsPanel({ user }) {
  return (
    <div className={panelClass}>
      <h2 className="mb-5 text-xl font-black tracking-tight text-white">Profile</h2>
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3 rounded-2xl border border-white/8 bg-white/[0.035] px-4 py-3">
          <span className="text-[14.7px] text-slate-400">Name</span>
          <span className="text-[14.7px] font-black text-white">{user.username}</span>
        </div>
        <div className="flex items-center justify-between gap-3 rounded-2xl border border-white/8 bg-white/[0.035] px-4 py-3">
          <span className="text-[14.7px] text-slate-400">Email</span>
          <span className="text-[14.7px] font-black text-white">{user.email}</span>
        </div>
        <div className="flex items-center justify-between gap-3 rounded-2xl border border-white/8 bg-white/[0.035] px-4 py-3">
          <span className="text-[14.7px] text-slate-400">Role</span>
          <span className="rounded-full border border-emerald-300/25 bg-emerald-500/10 px-3 py-1 text-[12.6px] font-black uppercase tracking-wide text-emerald-200">{user.role}</span>
        </div>
      </div>
    </div>
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
    <div className={panelClass}>
      <h2 className="mb-5 text-xl font-black tracking-tight text-white">Change password</h2>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className={labelClass}>Current password</label>
          <PasswordInput value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} autoComplete="current-password" required />
        </div>
        <div>
          <label className={labelClass}>New password</label>
          <PasswordInput value={newPassword} onChange={(e) => setNewPassword(e.target.value)} minLength={8} maxLength={32} autoComplete="new-password" required />
          <p className="mt-1 text-[11.6px] text-slate-600">8-32 characters, with uppercase, lowercase, a number, and a special character - no spaces</p>
        </div>
        <div>
          <label className={labelClass}>Confirm new password</label>
          <PasswordInput value={confirmNewPassword} onChange={(e) => setConfirmNewPassword(e.target.value)} autoComplete="new-password" required />
        </div>

        <Message error={error} success={success} />

        <button
          type="submit"
          disabled={submitting}
          className="rounded-xl bg-gradient-to-r from-emerald-600 to-teal-500 px-4 py-2.5 text-[14.7px] font-black text-white shadow-[0_16px_38px_rgba(16,185,129,0.3)] transition-all hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? 'Changing...' : 'Change password'}
        </button>
      </form>
    </div>
  )
}

export default function AdminProfilePage() {
  const { user, changePassword } = useAdminAuth()
  if (!user) return null

  return (
    <main className="relative mx-auto max-w-[720px] px-4 py-6 sm:px-6 lg:px-10">
      <h1 className="mb-6 text-3xl font-black tracking-tight text-white">Account</h1>
      <div className="space-y-6">
        <ProfileDetailsPanel user={user} />
        <ChangePasswordPanel changePassword={changePassword} />
      </div>
    </main>
  )
}
