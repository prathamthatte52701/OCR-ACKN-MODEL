import { useState } from 'react'
import Modal from './Modal'

const CHIPS = ['Not an employee', 'Duplicate account', 'Wrong email', 'Other']
const MAX = 300

// Reject (pending) / Revoke (approved) with an optional reason shown to the user on login.
// Plain text only; onConfirm gets the trimmed reason or null.
export default function RejectReasonModal({ user, revoke, busy, onConfirm, onClose }) {
  const [reason, setReason] = useState('')
  const verb = revoke ? 'Revoke' : 'Reject'

  return (
    <Modal onClose={() => { if (!busy) onClose() }}>
      <h2 className="text-lg font-bold text-white">{verb} {user.username}?</h2>
      <p className="mt-1 text-[14px] text-[var(--muted)]">
        Optional reason. The user sees it when they try to log in.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {CHIPS.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setReason(c === 'Other' ? '' : c)}
            className={`rounded-full border px-3 py-1 text-[13px] font-semibold transition-colors ${reason === c ? 'border-violet-300/60 bg-violet-500/25 text-white' : 'border-[var(--line)] bg-white/5 text-[var(--muted)] hover:text-white'}`}
          >
            {c}
          </button>
        ))}
      </div>
      <textarea
        value={reason}
        onChange={(e) => setReason(e.target.value.slice(0, MAX))}
        maxLength={MAX}
        rows={3}
        aria-label="Reason"
        placeholder="Reason (optional)"
        className="input mt-3 !py-2.5"
      />
      <p className="mt-1 text-right text-[13px] text-[var(--muted)]">{reason.length}/{MAX}</p>
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" disabled={busy} onClick={onClose} className="btn btn-ghost">
          Cancel
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onConfirm(reason.trim() || null)}
          className="btn btn-danger"
        >
          {busy ? 'Working...' : `Confirm ${verb.toLowerCase()}`}
        </button>
      </div>
    </Modal>
  )
}
