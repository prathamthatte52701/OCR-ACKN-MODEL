import { useState } from 'react'
import Modal from './Modal'
import PasswordInput from './PasswordInput'

// Shared by every admin nuke-delete variant (per-user age-based, global
// age-based, global year+month) - built on the same Modal wrapper as
// ConfirmModal/EditUserModal so it matches the rest of the admin app,
// but distinct from ConfirmModal (single-click) since this gates a
// genuinely irreversible cross-cutting delete: the admin's own password
// TWICE (must match) plus a typed confirmation phrase unique to the
// action, so a fat-fingered confirm can never trigger the wrong mode.
//
// DELIBERATELY NO Enter-to-submit anywhere in this component (unlike every
// other confirm/prompt dialog in the app) - Enter must never be able to
// fire handleDestroy() while tabbing/typing through these three fields,
// even once canSubmit is true. The nuke action is only ever reachable via
// an explicit click on the destroy button below. Esc-to-close still works
// normally (inherited from Modal) since cancelling is always safe.
export default function ConfirmPurgeModal({ title, message, phrase, purgeFn, extraBody, onClose, onDeleted, submitLabel = 'Permanently Delete', pendingLabel = 'Deleting...' }) {
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [typedPhrase, setTypedPhrase] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')

  function handleClose() {
    if (deleting) return
    onClose()
  }

  const passwordsEntered = password && confirmPassword
  const passwordsMismatch = passwordsEntered && password !== confirmPassword
  const canSubmit = typedPhrase === phrase && passwordsEntered && !passwordsMismatch && !deleting

  async function handleDestroy() {
    if (!canSubmit) return
    setDeleting(true)
    setError('')
    try {
      const result = await purgeFn({
        password,
        confirmPassword,
        confirmationPhrase: phrase,
        ...extraBody,
      })
      onDeleted(result)
    } catch (err) {
      setError(err.userMessage || 'Could not delete. Please try again.')
      setDeleting(false)
    }
  }

  return (
    <Modal onClose={handleClose} maxWidth="max-w-md">
      <h2 className="mb-2 text-lg font-black text-white">{title}</h2>
      <div className="mb-4 rounded-xl border border-amber-400/25 bg-amber-500/10 px-3.5 py-2.5 text-[12.6px] leading-5 text-amber-200">
        {message} This action <span className="font-black">CANNOT be undone</span> and there is
        no recovery path.
      </div>

      <div className="space-y-3.5">
        <div>
          <label className="mb-1 block text-[12.6px] font-semibold text-slate-400">Your password</label>
          <PasswordInput value={password} onChange={(e) => setPassword(e.target.value)} disabled={deleting} autoFocus autoComplete="current-password" />
        </div>
        <div>
          <label className="mb-1 block text-[12.6px] font-semibold text-slate-400">Re-enter your password to confirm</label>
          <PasswordInput value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} disabled={deleting} autoComplete="current-password" />
          {passwordsMismatch && <p className="mt-1 text-[12px] text-rose-400">Passwords do not match.</p>}
        </div>
        <div>
          <label className="mb-1 block text-[12.6px] font-semibold text-slate-400">
            Type <span className="font-mono font-bold text-rose-300">{phrase}</span> to confirm
          </label>
          <input
            type="text"
            value={typedPhrase}
            onChange={(e) => setTypedPhrase(e.target.value)}
            disabled={deleting}
            placeholder={phrase}
            className="w-full rounded-xl border border-white/10 bg-slate-950/60 px-3.5 py-2.5 text-[14.7px] text-white outline-none transition-colors focus:border-rose-400/60"
          />
        </div>
        {error && <p className="text-[13.6px] text-rose-400">{error}</p>}
      </div>

      <div className="mt-5 flex gap-3">
        <button
          type="button"
          onClick={handleDestroy}
          disabled={!canSubmit}
          className="rounded-xl bg-gradient-to-r from-rose-600 to-red-500 px-4 py-2.5 text-[14.7px] font-black text-white transition-all disabled:cursor-not-allowed disabled:opacity-50"
        >
          {deleting ? pendingLabel : submitLabel}
        </button>
        <button
          type="button"
          onClick={handleClose}
          disabled={deleting}
          className="rounded-xl border border-white/10 bg-white/[0.035] px-4 py-2.5 text-[14.7px] font-bold text-slate-300 hover:border-white/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </Modal>
  )
}
