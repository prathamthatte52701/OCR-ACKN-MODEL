import { useState } from 'react'
import { Link, useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import PasswordInput from '../components/PasswordInput'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(location.state?.success || '')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSuccess('')
    setSubmitting(true)
    try {
      await login(email, password)
      const next = searchParams.get('next')
      navigate(next && next.startsWith('/') ? next : '/', { replace: true })
    } catch (err) {
      setError(err.userMessage || 'Could not log in. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#020817] px-4">
      <div className="w-full max-w-sm rounded-[26px] border border-blue-300/18 bg-slate-900/62 p-7 shadow-[0_34px_120px_rgba(2,8,23,0.55)] backdrop-blur-xl">
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
              <Link to="/forgot-password" className="text-[12.6px] font-semibold text-blue-300 no-underline hover:text-blue-200">Forgot password?</Link>
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

        <p className="mt-5 text-center text-[13.6px] text-slate-500">
          No account? <Link to="/signup" className="font-semibold text-blue-300 no-underline hover:text-blue-200">Sign up</Link>
        </p>
      </div>
    </div>
  )
}
