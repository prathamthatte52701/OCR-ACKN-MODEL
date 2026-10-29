import { useRef, useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import { clearAllChats } from '../../api/chat'
import Banner from '../../components/Banner'
import Modal from '../../components/Modal'
import PasswordInput from '../../components/PasswordInput'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import { describeGlobalClearError, isTyped } from '../../utils/chatAdminCore'
import WarningIcon from './WarningIcon'

// PasswordInput keeps its own (old) base classes; these override them to the admin tokens.
const PW_CLASS = '!border-[var(--line)] !bg-[rgba(10,13,44,0.8)] !text-[var(--text)] focus:!border-[var(--violet-2)]'

// One step on purpose (password + the word DELETE, no dry run): a dry run spends the same
// 5-per-hour password budget as a real delete. Deliberately no Enter-to-submit, like the purge modal.
function DeleteAllChatsModal({ onClose, onDeleted }) {
  const bodyRef = useRef(null)
  useFocusTrap(bodyRef)
  const [password, setPassword] = useState('')
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const canDelete = password !== '' && isTyped(typed) && !busy

  async function remove() {
    if (!canDelete) return
    const attempt = password
    setPassword('') // gone from the screen and from state as soon as it is on its way
    setBusy(true)
    setError('')
    try {
      const res = await clearAllChats(attempt)
      onDeleted(res.deleted)
    } catch (err) {
      setError(describeGlobalClearError(err))
      setBusy(false)
    }
  }

  const close = () => { if (!busy) onClose() }

  return (
    <Modal onClose={close} maxWidth="max-w-md" ariaLabel="Delete all chat messages">
      <div ref={bodyRef}>
        <h2 className="mb-2 text-lg font-extrabold text-white">Delete ALL chat messages</h2>
        <div className="mb-4 rounded-xl border border-amber-400/35 bg-amber-400/10 px-3.5 py-2.5 text-[13px] leading-5 text-amber-200">
          This deletes every chat message between every user and every admin. It <span className="font-extrabold">CANNOT be undone</span>.
        </div>
        <div className="space-y-3.5">
          <div>
            <label htmlFor="chat-delete-password" className="ui-label mb-1 block">Your password</label>
            <PasswordInput id="chat-delete-password" className={PW_CLASS} value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy} autoComplete="current-password" />
          </div>
          <div>
            <label htmlFor="chat-delete-typed" className="ui-label mb-1 block">
              Type <span className="font-mono font-bold text-rose-300">DELETE</span> to confirm
            </label>
            <input id="chat-delete-typed" type="text" value={typed} onChange={(e) => setTyped(e.target.value)} disabled={busy} autoComplete="off" placeholder="DELETE" className="input" />
          </div>
          {error && <p role="alert" className="text-[14px] text-rose-300">{error}</p>}
        </div>
        <div className="mt-5 flex flex-wrap gap-3">
          <button type="button" onClick={remove} disabled={!canDelete} className="btn btn-danger">{busy ? 'Deleting...' : 'Delete all chat messages'}</button>
          <button type="button" onClick={close} disabled={busy} className="btn btn-ghost">Cancel</button>
        </div>
      </div>
    </Modal>
  )
}

export default function GlobalChatDeletePanel() {
  const [open, setOpen] = useState(false)
  const [success, setSuccess] = useState('')

  function handleDeleted(count) {
    setOpen(false)
    setSuccess(`Deleted ${count} chat ${count === 1 ? 'message' : 'messages'} across all users.`)
  }

  return (
    <div>
      <h3 className="mb-1 text-[16px] font-bold text-white">Delete all chat messages</h3>
      <p className="mb-4 text-[14px] leading-6 text-rose-100/80">
        Permanently deletes the chat between every user and every admin. Documents are not touched.
      </p>
      <Banner success={success} />
      <button type="button" onClick={() => { setSuccess(''); setOpen(true) }} className="btn btn-danger">
        <WarningIcon />
        Delete all chat messages...
      </button>
      <AnimatePresence>
        {open && <DeleteAllChatsModal onClose={() => setOpen(false)} onDeleted={handleDeleted} />}
      </AnimatePresence>
    </div>
  )
}
