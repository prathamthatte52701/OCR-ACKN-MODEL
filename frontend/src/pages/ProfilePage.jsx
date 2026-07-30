import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle } from 'lucide-react'
import { useAuth } from '../hooks/useAuth'
import { validateUsername, validateEmail, validatePassword } from '../utils/validators'
import PasswordInput from '../components/PasswordInput'
import { purgeAllData, purgeRange, purgeRangePreview } from '../api/documents'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog'

const inputClass = 'w-full rounded-xl border border-white/10 bg-slate-950/60 px-3.5 py-2.5 text-[14.7px] text-white outline-none transition-colors focus:border-blue-300/60'
const labelClass = 'mb-1 block text-[12.6px] font-semibold text-slate-400'
const panelClass = 'rounded-[28px] border border-blue-300/12 bg-slate-900/68 p-6 shadow-2xl shadow-slate-950/30 backdrop-blur-xl'

function Message({ error, success }) {
  if (!error && !success) return null
  return (
    <div className={`rounded-xl border px-3.5 py-2.5 text-[13.6px] ${error ? 'border-rose-400/25 bg-rose-500/10 text-rose-200' : 'border-emerald-400/25 bg-emerald-500/10 text-emerald-200'}`}>
      {error || success}
    </div>
  )
}

function ProfileDetailsPanel({ user, updateProfile }) {
  const [editing, setEditing] = useState(false)
  const [username, setUsername] = useState(user.username)
  const [email, setEmail] = useState(user.email)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [submitting, setSubmitting] = useState(false)

  function startEdit() {
    setUsername(user.username)
    setEmail(user.email)
    setError('')
    setSuccess('')
    setEditing(true)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSuccess('')

    const err = validateUsername(username) || validateEmail(email)
    if (err) { setError(err); return }

    setSubmitting(true)
    try {
      await updateProfile({ username, email: email.trim().toLowerCase() })
      setSuccess('Profile updated.')
      setEditing(false)
    } catch (err) {
      setError(err.userMessage || 'Could not update your profile. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={panelClass}>
      <div className="mb-5 flex items-center justify-between gap-3">
        <h2 className="text-xl font-black tracking-tight text-white">Profile</h2>
        {!editing && (
          <button
            type="button"
            onClick={startEdit}
            className="rounded-full border border-blue-300/20 bg-blue-500/10 px-4 py-2 text-[12.6px] font-black uppercase tracking-[0.14em] text-blue-200 transition-colors hover:bg-blue-500/15"
          >
            Edit
          </button>
        )}
      </div>

      {editing ? (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className={labelClass}>Username</label>
            <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} minLength={3} maxLength={8} required className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required className={inputClass} />
          </div>

          <Message error={error} success={success} />

          <div className="flex gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 px-4 py-2.5 text-[14.7px] font-black text-white shadow-[0_16px_38px_rgba(37,99,235,0.3)] transition-all hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? 'Saving...' : 'Save changes'}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-xl border border-white/10 bg-white/[0.035] px-4 py-2.5 text-[14.7px] font-bold text-slate-300 transition-colors hover:border-white/20"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-white/8 bg-white/[0.035] px-4 py-3">
            <span className="text-[14.7px] text-slate-400">Username</span>
            <span className="text-[14.7px] font-black text-white">{user.username}</span>
          </div>
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-white/8 bg-white/[0.035] px-4 py-3">
            <span className="text-[14.7px] text-slate-400">Email</span>
            <span className="text-[14.7px] font-black text-white">{user.email}</span>
          </div>
          <Message error={error} success={success} />
        </div>
      )}
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
          className="rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 px-4 py-2.5 text-[14.7px] font-black text-white shadow-[0_16px_38px_rgba(37,99,235,0.3)] transition-all hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? 'Changing...' : 'Change password'}
        </button>
      </form>
    </div>
  )
}

const CONFIRM_PHRASE = 'DELETE'

// Visually and structurally distinct from GlobalConfirmDialog on purpose -
// this is the single most destructive action in the app (irreversible full
// account wipe), so it gets its own red/critical theme and a typed-phrase
// gate instead of the shared one-click confirm dialog used everywhere else,
// so an accidental double-click can never trigger it.
function HardDeleteEverythingDialog({ open, onClose, onDeleted }) {
  const [password, setPassword] = useState('')
  const [phrase, setPhrase] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')

  function handleClose() {
    if (deleting) return
    setPassword('')
    setPhrase('')
    setError('')
    onClose()
  }

  async function handleDestroy() {
    if (phrase !== CONFIRM_PHRASE || !password) return
    setDeleting(true)
    setError('')
    try {
      const result = await purgeAllData({ password, confirmationPhrase: CONFIRM_PHRASE })
      onDeleted(result?.message)
    } catch (err) {
      setError(err.userMessage || 'Could not delete your data. Please try again.')
      setDeleting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) handleClose() }}>
      {open && (
        <DialogContent className="max-w-md border-red-500/40" showClose={!deleting}>
          <DialogHeader className="border-red-900/60 bg-red-950/30">
            <DialogTitle className="flex items-center gap-2 text-red-300">
              <AlertTriangle className="h-5 w-5 shrink-0" />
              Critical Warning
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 px-5 py-5">
            <p className="rounded-xl border border-red-800/60 bg-red-950/30 px-4 py-3 text-[13.6px] leading-6 text-red-200">
              This will permanently delete ALL your documents, workbooks, and export history.
              This action <span className="font-black">CANNOT be undone</span>. Please read
              this carefully before continuing.
            </p>
            <div>
              <label className="mb-1 block text-xs text-gray-400">Enter your password</label>
              <PasswordInput
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={deleting}
                autoFocus
                autoComplete="current-password"
                className="border-red-800/50 bg-gray-950 focus:border-red-500"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-400">
                Type <span className="font-mono font-bold text-red-300">{CONFIRM_PHRASE}</span> to confirm
              </label>
              <input
                type="text"
                value={phrase}
                onChange={(e) => setPhrase(e.target.value)}
                disabled={deleting}
                className="w-full rounded-lg border border-red-800/50 bg-gray-950 px-3 py-2.5 text-sm text-white outline-none transition-colors focus:border-red-500"
                placeholder={CONFIRM_PHRASE}
              />
            </div>
            {error && <p className="text-[13.6px] text-red-400">{error}</p>}
          </div>

          <DialogFooter>
            <button
              onClick={handleClose}
              disabled={deleting}
              className="rounded-lg bg-gray-800 px-4 py-2 text-sm text-gray-400 transition-colors hover:bg-gray-700 hover:text-gray-200 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleDestroy}
              disabled={phrase !== CONFIRM_PHRASE || !password || deleting}
              className="rounded-lg bg-red-700 px-4 py-2 text-sm font-bold text-white transition-colors hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {deleting ? 'Deleting Everything...' : 'Permanently Delete Everything'}
            </button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  )
}

const RANGE_CONFIRM_PHRASE = 'DELETE RANGE'

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(unitIndex > 0 ? 1 : 0)} ${units[unitIndex]}`
}

// Same password+phrase gate as HardDeleteEverythingDialog, distinct phrase
// ("DELETE RANGE" vs "DELETE") so a fat-fingered confirm can never trigger
// the wrong one of the two irreversible actions.
function DeleteRangeDialog({ open, onClose, onDeleted, rangeParams, preview }) {
  const [password, setPassword] = useState('')
  const [phrase, setPhrase] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')

  function handleClose() {
    if (deleting) return
    setPassword('')
    setPhrase('')
    setError('')
    onClose()
  }

  async function handleDestroy() {
    if (phrase !== RANGE_CONFIRM_PHRASE || !password) return
    setDeleting(true)
    setError('')
    try {
      const result = await purgeRange({
        password,
        confirmationPhrase: RANGE_CONFIRM_PHRASE,
        ...rangeParams,
      })
      onDeleted(result)
    } catch (err) {
      setError(err.userMessage || 'Could not delete these documents. Please try again.')
      setDeleting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) handleClose() }}>
      {open && (
        <DialogContent className="max-w-md border-red-500/40" showClose={!deleting}>
          <DialogHeader className="border-red-900/60 bg-red-950/30">
            <DialogTitle className="flex items-center gap-2 text-red-300">
              <AlertTriangle className="h-5 w-5 shrink-0" />
              Confirm Deletion
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 px-5 py-5">
            <p className="rounded-xl border border-red-800/60 bg-red-950/30 px-4 py-3 text-[13.6px] leading-6 text-red-200">
              This will permanently delete{' '}
              <span className="font-black">{preview?.count ?? '?'} document(s)</span> and their
              exported Excel rows. This action <span className="font-black">CANNOT be undone</span>.
            </p>
            <div>
              <label className="mb-1 block text-xs text-gray-400">Enter your password</label>
              <PasswordInput
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={deleting}
                autoFocus
                autoComplete="current-password"
                className="border-red-800/50 bg-gray-950 focus:border-red-500"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-400">
                Type <span className="font-mono font-bold text-red-300">{RANGE_CONFIRM_PHRASE}</span> to confirm
              </label>
              <input
                type="text"
                value={phrase}
                onChange={(e) => setPhrase(e.target.value)}
                disabled={deleting}
                className="w-full rounded-lg border border-red-800/50 bg-gray-950 px-3 py-2.5 text-sm text-white outline-none transition-colors focus:border-red-500"
                placeholder={RANGE_CONFIRM_PHRASE}
              />
            </div>
            {error && <p className="text-[13.6px] text-red-400">{error}</p>}
          </div>

          <DialogFooter>
            <button
              onClick={handleClose}
              disabled={deleting}
              className="rounded-lg bg-gray-800 px-4 py-2 text-sm text-gray-400 transition-colors hover:bg-gray-700 hover:text-gray-200 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleDestroy}
              disabled={phrase !== RANGE_CONFIRM_PHRASE || !password || deleting}
              className="rounded-lg bg-red-700 px-4 py-2 text-sm font-bold text-white transition-colors hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {deleting ? 'Deleting...' : 'Permanently Delete'}
            </button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  )
}

// Age-bucket (3/6/9 months) or specific-year partial delete. Preview is a
// read-only GET (no confirmation) so the user sees exactly what's about to
// go before the password+phrase dialog ever opens.
function DeleteOldDocumentsPanel() {
  const [mode, setMode] = useState('months')
  const [months, setMonths] = useState(6)
  const [year, setYear] = useState(new Date().getFullYear() - 1)
  const [preview, setPreview] = useState(null)
  const [previewing, setPreviewing] = useState(false)
  const [error, setError] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const queryClient = useQueryClient()

  const rangeParams = mode === 'months' ? { olderThanMonths: months } : { year: Number(year) }

  async function handlePreview() {
    setPreviewing(true)
    setError('')
    setPreview(null)
    try {
      setPreview(await purgeRangePreview(rangeParams))
    } catch (err) {
      setError(err.userMessage || 'Could not load a preview. Please try again.')
    } finally {
      setPreviewing(false)
    }
  }

  function handleDeleted(result) {
    setConfirmOpen(false)
    setPreview(null)
    queryClient.invalidateQueries()
    toast.success(result?.message || 'Old documents deleted.')
  }

  return (
    <div className="mt-4 rounded-2xl border border-red-900/40 bg-red-950/20 px-4 py-3.5">
      <p className="text-[14.7px] font-bold text-red-200">Delete Old Documents</p>
      <p className="mb-3 text-[12.6px] text-red-300/60">
        Permanently deletes documents (and their exported Excel rows) older than a chosen age, or from a specific year.
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1.5 text-[12.6px] text-red-200/80">
          <input
            type="radio"
            checked={mode === 'months'}
            onChange={() => { setMode('months'); setPreview(null) }}
          />
          Older than
        </label>
        <select
          value={months}
          onChange={(e) => { setMonths(Number(e.target.value)); setPreview(null) }}
          disabled={mode !== 'months'}
          className="rounded-lg border border-red-800/50 bg-gray-950 px-2 py-1.5 text-[12.6px] text-white disabled:opacity-40"
        >
          <option value={3}>3 months</option>
          <option value={6}>6 months</option>
          <option value={9}>9 months</option>
        </select>

        <label className="flex items-center gap-1.5 text-[12.6px] text-red-200/80">
          <input
            type="radio"
            checked={mode === 'year'}
            onChange={() => { setMode('year'); setPreview(null) }}
          />
          Specific year
        </label>
        <input
          type="number"
          value={year}
          onChange={(e) => { setYear(e.target.value); setPreview(null) }}
          disabled={mode !== 'year'}
          className="w-24 rounded-lg border border-red-800/50 bg-gray-950 px-2 py-1.5 text-[12.6px] text-white disabled:opacity-40"
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          onClick={handlePreview}
          disabled={previewing}
          className="rounded-lg border border-red-700 bg-red-900/40 px-3.5 py-2 text-[12.6px] font-bold text-red-200 transition-colors hover:bg-red-800/50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {previewing ? 'Checking...' : 'Preview'}
        </button>

        {preview && (
          <span className="text-[12.6px] text-red-200/80">
            {preview.count} document(s){preview.count > 0 && ` (~${formatBytes(preview.approxSizeBytes)})`}
          </span>
        )}

        {preview && preview.count > 0 && (
          <button
            onClick={() => setConfirmOpen(true)}
            className="rounded-lg bg-red-700 px-3.5 py-2 text-[12.6px] font-black text-white transition-colors hover:bg-red-600"
          >
            Delete These
          </button>
        )}
      </div>

      {error && <p className="mt-2 text-[12.6px] text-red-400">{error}</p>}

      <DeleteRangeDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onDeleted={handleDeleted}
        rangeParams={rangeParams}
        preview={preview}
      />
    </div>
  )
}

function DangerZonePanel() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  function handleDeleted(message) {
    setOpen(false)
    queryClient.clear()
    toast.success(message || 'All your data has been permanently deleted.')
    navigate('/')
  }

  return (
    <div className="rounded-[28px] border border-red-900/50 bg-red-950/10 p-6 shadow-2xl shadow-slate-950/30 backdrop-blur-xl">
      <h2 className="mb-1 text-xl font-black tracking-tight text-red-300">Danger Zone</h2>
      <p className="mb-5 text-[13.6px] text-red-200/70">
        Irreversible actions. Use only if you understand the consequences.
      </p>
      <div className="flex items-center justify-between gap-4 rounded-2xl border border-red-900/40 bg-red-950/20 px-4 py-3.5">
        <div>
          <p className="text-[14.7px] font-bold text-red-200">Hard Delete Everything</p>
          <p className="text-[12.6px] text-red-300/60">
            Permanently wipes every document, workbook, and export record you own.
          </p>
        </div>
        <button
          onClick={() => setOpen(true)}
          className="shrink-0 rounded-xl border border-red-700 bg-red-900/40 px-4 py-2.5 text-[13.6px] font-black text-red-200 transition-colors hover:bg-red-800/50"
        >
          Hard Delete Everything
        </button>
      </div>
      <HardDeleteEverythingDialog open={open} onClose={() => setOpen(false)} onDeleted={handleDeleted} />

      <DeleteOldDocumentsPanel />
    </div>
  )
}

export default function ProfilePage() {
  const { user, updateProfile, changePassword } = useAuth()
  if (!user) return null

  return (
    <main className="relative mx-auto max-w-[720px] px-4 py-6 sm:px-6 lg:px-10">
      <h1 className="mb-6 text-3xl font-black tracking-tight text-white">Account</h1>
      <div className="space-y-6">
        <ProfileDetailsPanel user={user} updateProfile={updateProfile} />
        <ChangePasswordPanel changePassword={changePassword} />
        <DangerZonePanel />
      </div>
    </main>
  )
}
