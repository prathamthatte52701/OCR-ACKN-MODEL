import { MAX_CHARS, countChars, isSubmitKey } from '../../utils/chatCore'

const COUNTER_FROM = 800
const FOCUS = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#7c6cff]'

export default function Composer({ userName, draft, onDraftChange, onSend, sending, error, disabled }) {
  const trimmed = draft.trim()
  const chars = countChars(draft)
  const canSend = trimmed !== '' && !sending && !disabled

  function submit() {
    if (canSend) onSend(trimmed)
  }

  return (
    <div className="space-y-2 border-t border-white/10 bg-[#0b0b0c] px-4 pb-3 pt-3">
      {error && <p role="alert" className="text-xs text-rose-300">{error}</p>}
      <textarea
        value={draft}
        rows={3}
        disabled={disabled}
        aria-label="Message"
        placeholder={userName ? `Reply to ${userName}` : 'Reply'}
        onChange={(e) => onDraftChange(e.target.value)}
        onKeyDown={(e) => {
          if (isSubmitKey(e)) {
            e.preventDefault()
            submit()
          }
        }}
        className={`block max-h-40 w-full resize-none rounded-xl border border-white/10 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 disabled:opacity-50 ${FOCUS}`}
      />
      <div className="flex items-center gap-2">
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
          className={`flex items-center gap-1.5 rounded-lg bg-[#4f46e5] px-3 py-1.5 text-xs font-bold text-white hover:bg-[#4338ca] disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS}`}
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" d="m22 2-7 20-4-9-9-4zM22 2 11 13" /></svg>
          {sending ? 'Sending...' : 'Send'}
        </button>
      </div>
    </div>
  )
}
