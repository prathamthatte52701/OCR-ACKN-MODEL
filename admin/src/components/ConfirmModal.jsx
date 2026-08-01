import Modal from './Modal'

// Shared confirm-before-destructive-action modal - built on the same Modal
// wrapper as EditUserModal/EditDocumentModal, so it matches the rest of the
// admin app instead of the browser's native confirm() dialog. Mount inside
// an <AnimatePresence> in the parent, same as every other Modal user here.
// `strong` renders a heavier amber warning strip for irreversible,
// data-affecting actions (e.g. purge-file) beyond the normal delete confirm.
export default function ConfirmModal({
  title = 'Are you sure?',
  message,
  confirmLabel = 'Yes, Delete',
  onConfirm,
  onClose,
  busy = false,
  strong = false,
}) {
  // Enter = confirm, mirroring the Confirm button - skipped when a button
  // already has focus so the browser's native Enter-activates-focused-button
  // behavior (e.g. tabbing to Cancel and hitting Enter) isn't double-fired.
  // Esc-to-close comes from Modal itself. Not used by ConfirmPurgeModal (the
  // nuke flow) - that component deliberately has no Enter handling at all.
  function handleKeyDown(e) {
    if (e.key !== 'Enter' || busy || e.target instanceof HTMLButtonElement) return
    e.preventDefault()
    onConfirm()
  }

  return (
    <Modal onClose={onClose}>
      <div onKeyDown={handleKeyDown}>
        <h2 className="mb-2 text-lg font-black text-white">{title}</h2>
        {strong && (
          <div className="mb-3 rounded-xl border border-amber-400/25 bg-amber-500/10 px-3.5 py-2.5 text-[12.6px] font-bold uppercase tracking-wide text-amber-200">
            This action is permanent and cannot be undone
          </div>
        )}
        <p className="mb-5 text-[14.7px] text-slate-400">{message}</p>
        <div className="flex gap-3">
          <button
            type="button"
            autoFocus
            onClick={onConfirm}
            disabled={busy}
            className="rounded-xl bg-gradient-to-r from-rose-600 to-red-500 px-4 py-2.5 text-[14.7px] font-black text-white transition-all disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? 'Working...' : confirmLabel}
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-xl border border-white/10 bg-white/[0.035] px-4 py-2.5 text-[14.7px] font-bold text-slate-300 hover:border-white/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </Modal>
  )
}
