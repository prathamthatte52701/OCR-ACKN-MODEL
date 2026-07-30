import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { validateUsername, validateEmail, validatePassword } from '../utils/validators'
import PasswordInput from '../components/PasswordInput'
import GoogleSignInButton from '../components/GoogleSignInButton'

export default function SignupPage() {
  const { signup } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')

    // Instant client-side feedback - backend re-validates everything anyway.
    const err = validateUsername(username) || validateEmail(email) || validatePassword(password)
    if (err) { setError(err); return }

    setSubmitting(true)
    try {
      await signup(username, email.trim().toLowerCase(), password)
      navigate('/login', { replace: true, state: { success: 'Account created — please log in.' } })
    } catch (err) {
      setError(err.userMessage || 'Could not create your account. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#020817] px-4 py-10">
      <div className="w-full max-w-sm rounded-[26px] border border-blue-300/18 bg-slate-900/62 p-7 shadow-[0_34px_120px_rgba(2,8,23,0.55)] backdrop-blur-xl">
        <div className="mb-6 text-center">
          <span className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-xl border border-blue-400/30 bg-blue-500/15 text-[14.7px] font-black text-blue-200">AI</span>
          <h1 className="text-2xl font-black text-white">Create account</h1>
          <p className="mt-1 text-[14.7px] text-slate-500">AckIntel AI</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-[12.6px] font-semibold text-slate-400">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              minLength={3}
              maxLength={8}
              autoComplete="username"
              required
              className="w-full rounded-xl border border-white/10 bg-slate-950/60 px-3.5 py-2.5 text-[14.7px] text-white outline-none transition-colors focus:border-blue-300/60"
            />
            <p className="mt-1 text-[11.6px] text-slate-600">3-8 characters</p>
          </div>
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
            <label className="mb-1 block text-[12.6px] font-semibold text-slate-400">Password</label>
            <PasswordInput
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              maxLength={32}
              autoComplete="new-password"
              required
            />
            <p className="mt-1 text-[11.6px] text-slate-600">8-32 characters, with uppercase, lowercase, a number, and a special character</p>
          </div>

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
            {submitting ? 'Creating account...' : 'Sign up'}
          </button>
        </form>

        <div className="my-5 flex items-center gap-3 text-[11.6px] font-semibold uppercase tracking-wide text-slate-600">
          <span className="h-px flex-1 bg-white/10" />
          or
          <span className="h-px flex-1 bg-white/10" />
        </div>
        <GoogleSignInButton />

        <p className="mt-5 text-center text-[13.6px] text-slate-500">
          Already have an account? <Link to="/login" className="font-semibold text-blue-300 no-underline hover:text-blue-200">Log in</Link>
        </p>
      </div>
    </div>
  )
}
