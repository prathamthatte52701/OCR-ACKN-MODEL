import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { changePassword } from '../api/auth'
import { useAuthStore } from '../store/authStore'
import { validatePassword } from '../utils/validators'
import PasswordInput from '../components/PasswordInput'

const labelClass = 'mb-1 block text-[12.6px] font-semibold text-slate-400'

// Full-screen forced change, shown (by ForcedPasswordGuard) for every route while
// user.mustChangePassword is true. Logout is the only other action.
export default function SetNewPasswordPage() {
  const navigate = useNavigate()
  const setSession = useAuthStore((s) => s.setSession)
  const clear = useAuthStore((s) => s.clear)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    const err = validatePassword(next)
    if (err) { setError(err); return }
    if (next !== confirm) { setError('New password and confirmation do not match.'); return }
    if (next === current) { setError('The new password must be different from the temporary password.'); return }
    setSubmitting(true)
    try {
      const data = await changePassword(current, next, confirm)
      // Fresh token (old ones were revoked) and a user with the flag cleared.
      setSession(data.token, data.user)
      navigate('/', { replace: true })
    } catch (e2) {
      setError(e2.userMessage || 'Could not change your password. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  function logout() {
    clear()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#020817] px-4">
      <div className="w-full max-w-sm rounded-[26px] border border-blue-300/18 bg-slate-900/62 p-7 shadow-[0_34px_120px_rgba(2,8,23,0.55)] backdrop-blur-xl">
        <div className="mb-6 text-center">
          <span className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-xl border border-blue-400/30 bg-blue-500/15 text-[14.7px] font-black text-blue-200">AI</span>
          <h1 className="text-2xl font-black text-white">Set a new password</h1>
          <p className="mt-1 text-[14.7px] text-slate-500">The admin gave you a temporary password. Choose your own to continue.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="snp-current" className={labelClass}>Temporary password</label>
            <PasswordInput id="snp-current" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
          </div>
          <div>
            <label htmlFor="snp-new" className={labelClass}>New password</label>
            <PasswordInput id="snp-new" value={next} onChange={(e) => setNext(e.target.value)} minLength={8} maxLength={64} autoComplete="new-password" required />
            <p className="mt-1 text-[11.6px] text-slate-600">8-64 characters, with uppercase, lowercase, a number, and a special character - no spaces. Must differ from the temporary password.</p>
          </div>
          <div>
            <label htmlFor="snp-confirm" className={labelClass}>Confirm new password</label>
            <PasswordInput id="snp-confirm" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
          </div>

          {error && (
            <div role="alert" className="rounded-xl border border-rose-400/25 bg-rose-500/10 px-3.5 py-2.5 text-[13.6px] text-rose-200">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 px-4 py-2.5 text-[14.7px] font-black text-white shadow-[0_16px_38px_rgba(37,99,235,0.3)] transition-all hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? 'Saving...' : 'Set new password'}
          </button>
        </form>

        <p className="mt-5 text-center text-[13.6px] text-slate-500">
          Signed in with Google? Use the temporary password the admin gave you.
        </p>
        <button type="button" onClick={logout} className="mt-3 block w-full text-center text-[13.6px] font-semibold text-blue-300 hover:text-blue-200">
          Log out
        </button>
      </div>
    </div>
  )
}
