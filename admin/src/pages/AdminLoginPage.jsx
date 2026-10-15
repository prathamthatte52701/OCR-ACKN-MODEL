import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAdminAuth } from '../context/AdminAuthContext'
import PasswordInput from '../components/PasswordInput'

export default function AdminLoginPage() {
  const { login } = useAdminAuth()
  const navigate = useNavigate()
  const location = useLocation()
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
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.userMessage || 'Could not log in. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="theme-admin relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-10">
      {/* soft violet / blue / pink glows behind the card */}
      <div aria-hidden="true" className="pointer-events-none absolute -left-40 top-[-10%] h-[520px] w-[520px] rounded-full bg-[rgba(124,58,237,0.38)] blur-[120px]" />
      <div aria-hidden="true" className="pointer-events-none absolute -right-32 bottom-[-12%] h-[480px] w-[480px] rounded-full bg-[rgba(79,107,255,0.3)] blur-[120px]" />
      <div aria-hidden="true" className="pointer-events-none absolute left-1/2 top-[55%] h-[320px] w-[320px] -translate-x-1/2 rounded-full bg-[rgba(236,72,153,0.14)] blur-[110px]" />

      <div className="ui-card relative w-full max-w-[400px] p-7 backdrop-blur-xl sm:p-8">
        <div className="mb-7 text-center">
          <svg className="mx-auto mb-3 h-12 w-12" viewBox="0 0 36 36" aria-hidden="true">
            <defs><linearGradient id="login-logo" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#a78bfa" /><stop offset="1" stopColor="#4f6bff" /></linearGradient></defs>
            <path d="M18 3 4 33h7l2.4-5.6h9.2L25 33h7z M15.6 22.4 18 16.6l2.4 5.8z" fill="url(#login-logo)" fillRule="evenodd" />
          </svg>
          <div className="text-[22px] font-extrabold tracking-tight text-white">ACKN <span className="text-[var(--violet-2)]">OCR</span></div>
          <h1 className="mt-1 text-[15px] font-semibold text-[var(--muted)]">Admin sign in</h1>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="login-email" className="ui-label mb-1 block">Email</label>
            <input
              id="login-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
              className="input"
            />
          </div>
          <div>
            <label htmlFor="login-password" className="ui-label mb-1 block">Password</label>
            <PasswordInput
              id="login-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>

          {success && (
            <div role="status" className="rounded-xl border border-emerald-400/35 bg-emerald-400/10 px-3.5 py-2.5 text-[14px] text-emerald-300">
              {success}
            </div>
          )}

          {error && (
            <div role="alert" className="rounded-xl border border-rose-400/40 bg-rose-400/10 px-3.5 py-2.5 text-[14px] text-rose-200">
              {error}
            </div>
          )}

          <button type="submit" disabled={submitting} className="btn btn-primary w-full" style={{ minHeight: 44 }}>
            {submitting ? 'Logging in...' : 'Log in'}
          </button>
        </form>

        <p className="mt-5 text-center text-[13px] text-[var(--muted)]">
          Admin accounts are provisioned by the system, not signed up here.
        </p>
      </div>
    </div>
  )
}
