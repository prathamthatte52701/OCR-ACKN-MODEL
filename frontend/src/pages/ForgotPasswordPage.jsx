import { useState } from 'react'
import { Link } from 'react-router-dom'
import { requestPasswordReset } from '../api/auth'
import { validateEmail } from '../utils/validators'
import BackButton from '../components/BackButton'

const inputClass = 'w-full rounded-xl border border-white/10 bg-slate-950/60 px-3.5 py-2.5 text-[14.7px] text-white outline-none transition-colors focus:border-blue-300/60'
const labelClass = 'mb-1 block text-[12.6px] font-semibold text-slate-400'
const NOTE_MAX = 200

// One form. The server always answers with the same generic message, so the page never
// reveals whether the email belongs to an account.
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    const emailErr = validateEmail(email)
    if (emailErr) { setError(emailErr); return }
    setSubmitting(true)
    try {
      const data = await requestPasswordReset(email.trim().toLowerCase(), note.trim())
      setDone(data?.message || 'If this account exists, the admin has been told.')
    } catch (err) {
      setError(err.userMessage || 'Could not send the request. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#020817] px-4">
      <div className="w-full max-w-sm rounded-[26px] border border-blue-300/18 bg-slate-900/62 p-7 shadow-[0_34px_120px_rgba(2,8,23,0.55)] backdrop-blur-xl">
        <BackButton fallback="/login" />
        <div className="mb-6 text-center">
          <span className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-xl border border-blue-400/30 bg-blue-500/15 text-[14.7px] font-black text-blue-200">AI</span>
          <h1 className="text-2xl font-black text-white">Request password reset</h1>
          <p className="mt-1 text-[14.7px] text-slate-500">The admin will give you a temporary password.</p>
        </div>

        {done ? (
          <div role="status" className="rounded-xl border border-emerald-400/25 bg-emerald-500/10 px-3.5 py-3 text-[14px] text-emerald-200">
            {done}
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div>
              <label htmlFor="reset-email" className={labelClass}>Email</label>
              <input id="reset-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} required autoComplete="email" className={inputClass} />
            </div>
            <div>
              <label htmlFor="reset-note" className={labelClass}>Note for the admin (optional)</label>
              <textarea id="reset-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={NOTE_MAX} rows={3} className={inputClass} />
              <p className="mt-1 text-right text-[11.6px] text-slate-600">{note.length}/{NOTE_MAX}</p>
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
              {submitting ? 'Sending...' : 'Send request'}
            </button>
          </form>
        )}

        <p className="mt-5 text-center text-[13.6px] text-slate-500">
          <Link to="/login" className="font-semibold text-blue-300 no-underline hover:text-blue-200">Back to log in</Link>
        </p>
      </div>
    </div>
  )
}
