import { useRef } from 'react'
import { ListPlus, Paperclip, Send } from 'lucide-react'
import { MAX_CHARS, canSend as canSendCore, clampText, countChars, isSubmitKey } from '../../utils/chatCore'
import FileChip from './FileChip'
import AdminPicker from './AdminPicker'

const COUNTER_FROM = 800

export default function Composer({
  textareaRef, draft, onDraftChange, onSend, sending, error,
  admins, adminsState, selectedAdminId, onSelectAdmin, onInsertSummary, summaryError,
  file, onFileChange, fileError, progress,
}) {
  const inputRef = useRef(null)
  const trimmed = draft.trim()
  const chars = countChars(draft)
  const noAdmin = adminsState !== 'ready' || admins.length === 0
  const canSend = canSendCore({ text: draft, file }) && !sending && !noAdmin

  function submit() {
    if (canSend) onSend(trimmed)
  }

  function pick(e) {
    onFileChange(e.target.files?.[0] ?? null)
    e.target.value = '' // choosing the same file again must still fire
  }

  return (
    <div className="space-y-2 border-t border-white/10 bg-[#0b0b0c] pb-3 pt-2">
      <AdminPicker admins={admins} state={adminsState} selectedId={selectedAdminId} onSelect={onSelectAdmin} />
      {error && <p role="alert" className="px-4 text-xs text-rose-300">{error}</p>}
      {fileError && <p role="alert" className="px-4 text-xs text-rose-300">{fileError}</p>}
      {summaryError && <p role="alert" className="px-4 text-xs text-rose-300">Could not load today&apos;s numbers.</p>}
      {file && <FileChip file={file} disabled={sending} onRemove={() => onFileChange(null)} />}
      <div className="px-4">
        <textarea
          ref={textareaRef}
          value={draft}
          rows={3}
          disabled={noAdmin}
          aria-label="Message"
          placeholder={file ? 'Add a caption (optional)' : 'Write to your admin'}
          onChange={(e) => onDraftChange(clampText(e.target.value))}
          onKeyDown={(e) => {
            if (isSubmitKey(e)) {
              e.preventDefault()
              submit()
            }
          }}
          className="block max-h-40 w-full resize-none rounded-xl border border-white/10 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 disabled:opacity-50"
        />
      </div>
      <div className="flex items-center gap-2 px-4">
        <button
          type="button"
          onClick={onInsertSummary}
          disabled={noAdmin}
          className="flex min-w-0 items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs font-semibold text-zinc-300 hover:bg-white/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 disabled:opacity-50"
        >
          <ListPlus className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="truncate">Insert today&apos;s summary</span>
        </button>
        <input ref={inputRef} type="file" hidden accept=".jpg,.jpeg,.png,.webp,.pdf" onChange={pick} />
        <button
          type="button"
          aria-label="Attach a file"
          onClick={() => inputRef.current?.click()}
          disabled={noAdmin || sending}
          className="rounded-lg border border-white/10 p-1.5 text-zinc-300 hover:bg-white/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 disabled:opacity-50"
        >
          <Paperclip className="h-4 w-4" aria-hidden="true" />
        </button>
        <span className="flex-1" />
        {chars > COUNTER_FROM && (
          <span className={`text-xs tabular-nums ${chars >= MAX_CHARS ? 'text-rose-300' : 'text-zinc-400'}`}>
            {chars}/{MAX_CHARS}
          </span>
        )}
        <button
          type="button"
          onClick={submit}
          disabled={!canSend}
          className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-blue-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Send className="h-4 w-4" aria-hidden="true" />
          {sending ? (file && progress > 0 && progress < 100 ? `Sending ${progress}%` : 'Sending...') : 'Send'}
        </button>
      </div>
    </div>
  )
}
