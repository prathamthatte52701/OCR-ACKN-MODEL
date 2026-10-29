import { useRef, useState } from 'react'
import { clearThread } from '../../api/chat'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import { CLEAR_RANGES, clearSummary, createTokens, isTyped } from '../../utils/chatAdminCore'
import Modal from '../Modal'

// Deletes one user's chat by age. Every range change asks the server for a dry-run count first; the
// Delete button stays off until that count is in, is above zero and the word DELETE is typed.
export default function ClearChatModal({ user, onClose, onCleared }) {
  const bodyRef = useRef(null)
  useFocusTrap(bodyRef)
  const [tokens] = useState(createTokens)
  const [range, setRange] = useState(null)
  const [count, setCount] = useState(null) // { range, n } | { range, failed: true }
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [deleted, setDeleted] = useState(null)

  function pickRange(id) {
    setRange(id)
    setCount(null)
    setError('')
    const token = tokens.next()
    clearThread(user.userId, id, true).then(
      (res) => { if (tokens.isCurrent(token)) setCount({ range: id, n: res.count }) },
      () => { if (tokens.isCurrent(token)) setCount({ range: id, failed: true }) },
    )
  }

  const counted = count && count.range === range && !count.failed ? count.n : null
  const canDelete = counted > 0 && isTyped(typed) && !busy

  async function remove() {
    if (!canDelete) return
    setBusy(true)
    setError('')
    try {
      const res = await clearThread(user.userId, range, false)
      setDeleted(res.deleted)
      onCleared()
    } catch (err) {
      setError(err.userMessage || 'Could not delete the messages. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  function close() {
    if (!busy) onClose()
  }

  let status = ''
  if (range && counted !== null) status = clearSummary(range, counted)
  else if (range && count?.failed) status = 'Could not count the messages. Pick the range again.'
  else if (range) status = 'Counting messages...'

  return (
    <Modal onClose={close} maxWidth="max-w-md" ariaLabel={`Clear chat with ${user.name}`}>
      <div ref={bodyRef}>
        <h2 className="mb-1 text-lg font-extrabold text-white">Clear chat with {user.name}</h2>
        {deleted !== null ? (
          <>
            <p role="status" className="mb-5 text-[14px] text-teal-200">
              Deleted {deleted} {deleted === 1 ? 'message' : 'messages'}.
            </p>
            <button type="button" onClick={onClose} className="btn btn-ghost">Close</button>
          </>
        ) : (
          <>
            <p className="mb-3 text-[13px] text-[var(--muted)]">Only this user&apos;s chat is affected. This cannot be undone.</p>
            <div role="radiogroup" aria-label="Delete messages" className="mb-3 grid gap-1.5">
              {CLEAR_RANGES.map((r) => (
                <label key={r.id} className="flex cursor-pointer items-center gap-2 text-[14px] text-white">
                  <input
                    type="radio"
                    name="clear-range"
                    className="h-4 w-4 accent-[var(--red-strong)]"
                    checked={range === r.id}
                    disabled={busy}
                    onChange={() => pickRange(r.id)}
                  />
                  {r.label}
                </label>
              ))}
            </div>
            <p role="status" aria-live="polite" className="mb-3 min-h-5 text-[14px] font-semibold text-amber-200">{status}</p>
            <label htmlFor="clear-typed" className="ui-label mb-1 block">
              Type <span className="font-mono font-bold text-rose-300">DELETE</span> to confirm
            </label>
            <input
              id="clear-typed"
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              disabled={busy}
              autoComplete="off"
              placeholder="DELETE"
              className="input"
            />
            {error && <p role="alert" className="mt-2 text-[14px] text-rose-300">{error}</p>}
            <div className="mt-5 flex flex-wrap gap-3">
              <button type="button" onClick={remove} disabled={!canDelete} className="btn btn-danger">
                {busy ? 'Deleting...' : 'Delete messages'}
              </button>
              <button type="button" onClick={close} disabled={busy} className="btn btn-ghost">Cancel</button>
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}
