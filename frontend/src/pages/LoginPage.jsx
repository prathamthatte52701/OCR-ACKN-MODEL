import { useState } from 'react'
import { Link, useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import PasswordInput from '../components/PasswordInput'
import GoogleSignInButton from '../components/GoogleSignInButton'
import { formatLocal } from '../utils/formatDate'
import { safeNext } from '../utils/safeNext'
import BackButton from '../components/BackButton'

// Plain-text status card for a 403 login (pending / rejected / revoked). Text nodes only -
// the admin's reason is user-controlled data and is never rendered as HTML.
function statusText(d) {
  const reason = d.reason || 'No reason was given'
  if (d.code === 'ACCOUNT_PENDING') {
    const when = formatLocal(d.requestedAt)
    return `${when ? `Your request was sent on ${when}. ` : ''}The admin has not decided yet. Log in again later to check. No email is sent.`
  }
  if (d.code === 'ACCOUNT_REJECTED') {
    return `Your request was not approved${d.decidedAt ? ` on ${formatLocal(d.decidedAt)}` : ''}. Reason: ${reason}. Contact your admin.`
  }
  if (d.code === 'ACCOUNT_REVOKED') {
    return `Your access was removed${d.decidedAt ? ` on ${formatLocal(d.decidedAt)}` : ''}. Reason: ${reason}. Contact your admin.`
  }
  return d.message || ''
}

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  // 403 = pending/rejected account (not a typo in the password) - shown as an
  // amber notice with the server's own wording instead of a red error.
  const [notice, setNotice] = useState(searchParams.get('notice') || '')
  const [success, setSuccess] = useState(location.state?.success || '')
  const [submitting, setSubmitting] = useState(false)

  // Back from the pending/rejected/revoked card: return to a clean form.
  function backToForm() {
    setError('')
    setNotice('')
    setSuccess('')
    setPassword('')
    navigate('/login', { replace: true })
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setNotice('')
    setSuccess('')
    setSubmitting(true)
    try {
      await login(email, password)
      const next = searchParams.get('next')
      navigate(safeNext(next), { replace: true })
    } catch (err) {
      const detail = err.response?.data?.detail
      if (err.response?.status === 403 && typeof detail?.code === 'string') setNotice(statusText(detail))
      else if (err.response?.status === 403) setNotice(err.userMessage)
      else setError(err.userMessage || 'Could not log in. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#020817] px-4">
      <div className="w-full max-w-sm rounded-[26px] border border-blue-300/18 bg-slate-900/62 p-7 shadow-[0_34px_120px_rgba(2,8,23,0.55)] backdrop-blur-xl">
        {notice && <BackButton onBack={backToForm} />}
        <div className="mb-6 text-center">
          <span className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-xl border border-blue-400/30 bg-blue-500/15 text-[14.7px] font-black text-blue-200">AI</span>
          <h1 className="text-2xl font-black text-white">Log in</h1>
          <p className="mt-1 text-[14.7px] text-slate-500">AckIntel AI</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-[12.6px] font-semibold text-slate-400">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
              className="w-full rounded-xl border border-white/10 bg-slate-950/60 px-3.5 py-2.5 text-[14.7px] text-white outline-none transition-colors focus:border-blue-300/60"
            />
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between">
              <label className="block text-[12.6px] font-semibold text-slate-400">Password</label>
              <Link to="/forgot-password" className="text-[12.6px] font-semibold text-blue-300 no-underline hover:text-blue-200">Request password reset</Link>
            </div>
            <PasswordInput
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>

          {success && (
            <div className="rounded-xl border border-emerald-400/25 bg-emerald-500/10 px-3.5 py-2.5 text-[13.6px] text-emerald-200">
              {success}
            </div>
          )}

          {notice && (
            <div role="status" data-testid="account-status" className="break-words rounded-xl border border-amber-400/30 bg-amber-500/10 px-3.5 py-2.5 text-[13.6px] text-amber-200">
              {notice}
            </div>
          )}

          {error && (
            <div className="rounded-xl border border-rose-400/25 bg-rose-500/10 px-3.5 py-2.5 text-[13.6px] text-rose-200">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 px-4 py-2.5 text-[14.7px] font-black text-white shadow-[0_16px_38px_rgba(37,99,235,0.3)] transition-all hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? 'Logging in...' : 'Log in'}
          </button>
        </form>

        <div className="my-5 flex items-center gap-3 text-[11.6px] font-semibold uppercase tracking-wide text-slate-600">
          <span className="h-px flex-1 bg-white/10" />
          or
          <span className="h-px flex-1 bg-white/10" />
        </div>
        <GoogleSignInButton />

        <p className="mt-5 text-center text-[13.6px] text-slate-500">
          No account? <Link to="/signup" className="font-semibold text-blue-300 no-underline hover:text-blue-200">Sign up</Link>
        </p>
      </div>
    </div>
  )
}
