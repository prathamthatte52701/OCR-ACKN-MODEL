import { useRef, useState } from 'react'
import useDialogStore from '../store/dialogStore'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from './ui/dialog'

// Mounted once in App.jsx - renders whenever confirmAction() from
// store/dialogStore is called anywhere in the app (replaces window.confirm()
// and the old ConfirmModal component with one shared, styled dialog).
export default function GlobalConfirmDialog() {
  const confirmState = useDialogStore((s) => s.confirmState)
  const resolveConfirm = useDialogStore((s) => s.resolveConfirm)
  const [busy, setBusy] = useState(false)
  const confirmButtonRef = useRef(null)

  const open = Boolean(confirmState)

  async function handleConfirm() {
    setBusy(true)
    resolveConfirm(true)
    setBusy(false)
  }

  // Enter = confirm, mirroring the Confirm button - skipped when a button
  // already has focus so the browser's own Enter-activates-focused-button
  // behavior (e.g. tabbing to Cancel and hitting Enter) isn't double-fired
  // by this handler too. Esc-to-close is handled by Radix itself via
  // onOpenChange below, no extra code needed for that.
  function handleKeyDown(e) {
    if (e.key !== 'Enter' || busy || e.target instanceof HTMLButtonElement) return
    e.preventDefault()
    handleConfirm()
  }

  // Radix focuses the first focusable descendant on open by default, which
  // would otherwise be the Cancel button (it's first in DOM order) - that
  // makes a plain Enter press fire Cancel instead of Confirm. Redirect
  // initial focus to the Confirm button instead, so Enter does the right
  // thing whether it's caught by handleKeyDown above or by the browser's
  // own focused-button-activates-on-Enter behavior.
  function handleOpenAutoFocus(e) {
    e.preventDefault()
    confirmButtonRef.current?.focus()
  }

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) resolveConfirm(false) }}>
      {open && (
        <DialogContent
          className="max-w-sm"
          showClose={false}
          onKeyDown={handleKeyDown}
          onOpenAutoFocus={handleOpenAutoFocus}
        >
          <DialogHeader>
            <DialogTitle>{confirmState.title}</DialogTitle>
          </DialogHeader>
          <div className="px-5 py-4">
            <p className="text-sm text-gray-300">{confirmState.message}</p>
          </div>
          <DialogFooter>
            <button
              onClick={() => resolveConfirm(false)}
              disabled={busy}
              className="rounded-lg bg-gray-800 px-4 py-2 text-sm text-gray-400 transition-colors hover:bg-gray-700 hover:text-gray-200 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              ref={confirmButtonRef}
              onClick={handleConfirm}
              disabled={busy}
              className={`rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                confirmState.danger ? 'bg-red-700 hover:bg-red-600' : 'bg-blue-600 hover:bg-blue-700'
              }`}
            >
              {confirmState.confirmLabel}
            </button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  )
}
