import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../utils/api'
import { validatePassword } from '../utils/validators'
import PasswordInput from '../components/PasswordInput'

const inputClass = 'w-full rounded-xl border border-white/10 bg-slate-950/60 px-3.5 py-2.5 text-[14.7px] text-white outline-none transition-colors focus:border-emerald-300/60'
const labelClass = 'mb-1 block text-[12.6px] font-semibold text-slate-400'

export default function AdminForgotPasswordPage() {
  const navigate = useNavigate()
  const [verified, setVerified] = useState(false)
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmNewPassword, setConfirmNewPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleVerify(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await api.post('/auth/forgot-password/verify', { username, email: email.trim().toLowerCase() })
      setVerified(true)
    } catch (err) {
      setError(err.userMessage || 'Username and email do not match our records.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleReset(e) {
    e.preventDefault()
    setError('')

    const passwordErr = validatePassword(newPassword)
    if (passwordErr) { setError(passwordErr); return }
    if (newPassword !== confirmNewPassword) { setError('New password and confirmation do not match.'); return }

    setSubmitting(true)
    try {
      await api.post('/auth/forgot-password/reset', {
        username,
        email: email.trim().toLowerCase(),
        newPassword,
        confirmNewPassword,
      })
      navigate('/login', { replace: true, state: { success: 'Password updated successfully. Please log in.' } })
    } catch (err) {
      setError(err.userMessage || 'Could not reset your password. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#04070d] px-4">
      <div className="w-full max-w-sm rounded-[26px] border border-emerald-300/18 bg-slate-900/62 p-7 shadow-[0_34px_120px_rgba(2,8,23,0.55)] backdrop-blur-xl">
        <div className="mb-6 text-center">
          <span className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-xl border border-emerald-400/30 bg-emerald-500/15 text-[14.7px] font-black text-emerald-200">AD</span>
          <h1 className="text-2xl font-black text-white">{verified ? 'Set new password' : 'Forgot password'}</h1>
          <p className="mt-1 text-[14.7px] text-slate-500">
            {verified ? 'Choose a new password for your account.' : 'Verify your username and email to reset your password.'}
          </p>
        </div>

        {!verified ? (
          <form onSubmit={handleVerify} className="space-y-4">
            <div>
              <label className={labelClass}>Username</label>
              <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} required className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required className={inputClass} />
            </div>

            {error && (
              <div className="rounded-xl border border-rose-400/25 bg-rose-500/10 px-3.5 py-2.5 text-[13.6px] text-rose-200">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-xl bg-gradient-to-r from-emerald-600 to-teal-500 px-4 py-2.5 text-[14.7px] font-black text-white shadow-[0_16px_38px_rgba(16,185,129,0.3)] transition-all hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? 'Verifying...' : 'Verify'}
            </button>
          </form>
        ) : (
          <form onSubmit={handleReset} className="space-y-4">
            <div>
              <label className={labelClass}>New password</label>
              <PasswordInput value={newPassword} onChange={(e) => setNewPassword(e.target.value)} minLength={8} maxLength={32} autoComplete="new-password" required />
              <p className="mt-1 text-[11.6px] text-slate-600">8-32 characters, with uppercase, lowercase, a number, and a special character - no spaces</p>
            </div>
            <div>
              <label className={labelClass}>Confirm new password</label>
              <PasswordInput value={confirmNewPassword} onChange={(e) => setConfirmNewPassword(e.target.value)} autoComplete="new-password" required />
            </div>

            {error && (
              <div className="rounded-xl border border-rose-400/25 bg-rose-500/10 px-3.5 py-2.5 text-[13.6px] text-rose-200">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-xl bg-gradient-to-r from-emerald-600 to-teal-500 px-4 py-2.5 text-[14.7px] font-black text-white shadow-[0_16px_38px_rgba(16,185,129,0.3)] transition-all hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? 'Updating...' : 'Update password'}
            </button>
          </form>
        )}

        <p className="mt-5 text-center text-[13.6px] text-slate-500">
          <Link to="/login" className="font-semibold text-emerald-300 no-underline hover:text-emerald-200">Back to log in</Link>
        </p>
      </div>
    </div>
  )
}
