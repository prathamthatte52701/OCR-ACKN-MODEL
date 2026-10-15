import { useState } from 'react'
import Modal from './Modal'
import PasswordInput from './PasswordInput'

// PasswordInput keeps its own (old) base classes; these override them to the admin tokens.
const PW_CLASS = '!border-[var(--line)] !bg-[rgba(10,13,44,0.8)] !text-[var(--text)] focus:!border-[var(--violet-2)]'

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
      <h2 className="mb-2 text-lg font-extrabold text-white">{title}</h2>
      <div className="mb-4 rounded-xl border border-amber-400/35 bg-amber-400/10 px-3.5 py-2.5 text-[13px] leading-5 text-amber-200">
        {message} This action <span className="font-extrabold">CANNOT be undone</span> and there is
        no recovery path.
      </div>

      <div className="space-y-3.5">
        <div>
          <label className="ui-label mb-1 block">Your password</label>
          <PasswordInput className={PW_CLASS} value={password} onChange={(e) => setPassword(e.target.value)} disabled={deleting} autoFocus autoComplete="current-password" />
        </div>
        <div>
          <label className="ui-label mb-1 block">Re-enter your password to confirm</label>
          <PasswordInput className={PW_CLASS} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} disabled={deleting} autoComplete="current-password" />
          {passwordsMismatch && <p className="mt-1 text-[13px] text-rose-300">Passwords do not match.</p>}
        </div>
        <div>
          <label className="ui-label mb-1 block">
            Type <span className="font-mono font-bold text-rose-300">{phrase}</span> to confirm
          </label>
          <input
            type="text"
            value={typedPhrase}
            onChange={(e) => setTypedPhrase(e.target.value)}
            disabled={deleting}
            placeholder={phrase}
            className="input"
          />
        </div>
        {error && <p className="text-[14px] text-rose-300">{error}</p>}
      </div>

      <div className="mt-5 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={handleDestroy}
          disabled={!canSubmit}
          className="btn btn-danger"
        >
          {deleting ? pendingLabel : submitLabel}
        </button>
        <button
          type="button"
          onClick={handleClose}
          disabled={deleting}
          className="btn btn-ghost"
        >
          Cancel
        </button>
      </div>
    </Modal>
  )
}
