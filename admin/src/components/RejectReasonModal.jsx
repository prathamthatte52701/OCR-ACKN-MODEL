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
      <h2 className="text-lg font-black text-white">{verb} {user.username}?</h2>
      <p className="mt-1 text-[13.6px] text-slate-400">
        Optional reason. The user sees it when they try to log in.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {CHIPS.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setReason(c === 'Other' ? '' : c)}
            className={`rounded-full border px-3 py-1 text-[12.6px] font-bold ${reason === c ? 'border-emerald-300/50 bg-emerald-500/15 text-emerald-200' : 'border-white/10 bg-white/[0.035] text-slate-300 hover:border-emerald-300/30'}`}
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
        className="mt-3 w-full rounded-xl border border-white/10 bg-slate-950/60 px-3 py-2 text-[13.6px] text-white outline-none focus:border-emerald-300/50"
      />
      <p className="mt-1 text-right text-[11.6px] text-slate-500">{reason.length}/{MAX}</p>
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" disabled={busy} onClick={onClose} className="rounded-full border border-white/10 px-4 py-2 text-[13.6px] font-bold text-slate-300 disabled:opacity-50">
          Cancel
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onConfirm(reason.trim() || null)}
          className="rounded-full border border-rose-300/30 bg-rose-500/15 px-4 py-2 text-[13.6px] font-bold text-rose-200 disabled:opacity-50"
        >
          {busy ? 'Working...' : `Confirm ${verb.toLowerCase()}`}
        </button>
      </div>
    </Modal>
  )
}
