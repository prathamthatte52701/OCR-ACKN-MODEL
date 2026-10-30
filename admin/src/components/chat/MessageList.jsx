import { Fragment, useLayoutEffect, useRef, useState } from 'react'
import { MAX_CHARS, canEditNow, clampText, countChars, isSubmitKey } from '../../utils/chatCore'
import { NEUTRAL_BUBBLE, OWN_BUBBLE } from '../../utils/chatColors'
import { dayKeyIST, formatIST } from '../../utils/formatDate'
import Attachment from './Attachment'

const NEAR_BOTTOM_PX = 40
const TIME_ONLY = { day: undefined, month: undefined, year: undefined }
const DATE_ONLY = { hour: undefined, minute: undefined, hour12: undefined }
const FOCUS = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400'

function EditBox({ initial, saving, error, onSave, onCancel }) {
  const [text, setText] = useState(initial)
  const trimmed = text.trim()
  return (
    <div className="w-full space-y-1.5">
      <textarea
        autoFocus
        value={text}
        rows={3}
        aria-label="Edit message"
        onChange={(e) => setText(clampText(e.target.value))}
        onKeyDown={(e) => {
          if (isSubmitKey(e)) {
            e.preventDefault()
            if (trimmed && !saving) onSave(trimmed)
          } else if (e.key === 'Escape') {
            e.stopPropagation()
            onCancel()
          }
        }}
        className={`block w-full resize-none rounded-xl border border-white/10 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 ${FOCUS}`}
      />
      {error && <p role="alert" className="text-xs text-rose-300">{error}</p>}
      <div className="flex items-center justify-end gap-2">
        <span className="mr-auto text-xs tabular-nums text-zinc-500">{countChars(text)}/{MAX_CHARS}</span>
        <button type="button" onClick={onCancel} className={`rounded-md px-2.5 py-1 text-xs font-semibold text-zinc-300 hover:bg-white/[0.06] ${FOCUS}`}>
          Cancel
        </button>
        <button
          type="button"
          disabled={!trimmed || saving}
          onClick={() => onSave(trimmed)}
          className={`rounded-md bg-blue-600 px-2.5 py-1 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-50 ${FOCUS}`}
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </div>
  )
}

function MessageItem({ message: m, files, canEdit, editing, edit, onStartEdit, onCancelEdit, onSaveEdit }) {
  const palette = m.mine ? OWN_BUBBLE : NEUTRAL_BUBBLE
  return (
    <div className={`flex flex-col ${m.mine ? 'items-end' : 'items-start'}`}>
      {!m.mine && <span className="mb-0.5 px-1 text-xs font-semibold text-zinc-400">{m.fromName}</span>}
      {m.attachment && <Attachment att={m.attachment} files={files} />}
      {editing ? (
        <EditBox initial={m.text} saving={edit.saving} error={edit.error} onSave={onSaveEdit} onCancel={onCancelEdit} />
      ) : m.text ? (
        <div
          style={{ backgroundColor: palette.bubble, color: palette.text }}
          className="max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm [overflow-wrap:anywhere]"
        >
          {m.text}
        </div>
      ) : null}
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 px-1 text-[11px] text-zinc-500">
        <span>{formatIST(m.createdAt, TIME_ONLY)}</span>
        {m.editedAt && <span>edited</span>}
        {m.mine && m.readAt && <span>Seen</span>}
        {canEdit && !editing && (
          <button type="button" onClick={() => onStartEdit(m.id)} className={`rounded font-semibold text-zinc-300 underline-offset-2 hover:underline ${FOCUS}`}>
            Edit
          </button>
        )}
      </div>
    </div>
  )
}

export default function MessageList({
  messages, offset, now, files, expiredEdits, edit, onStartEdit, onCancelEdit, onSaveEdit,
  hasOlder, loadingOlder, onLoadOlder, onAtBottomChange, loading,
}) {
  const scrollRef = useRef(null)
  const atBottomRef = useRef(true)
  const shown = useRef({ first: null, last: null, height: 0 })
  const [atBottom, setAtBottom] = useState(true)
  const [seenLast, setSeenLast] = useState(null)
  const lastId = messages.length ? messages[messages.length - 1].id : null

  function scrollToBottom() {
    const el = scrollRef.current
    el.scrollTop = el.scrollHeight
  }

  function onScroll() {
    const el = scrollRef.current
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX
    atBottomRef.current = bottom
    setAtBottom(bottom)
    onAtBottomChange(bottom)
    if (bottom) setSeenLast(lastId)
  }

  // Stick to the bottom for new messages when already there (or when the user just sent one);
  // keep the reading position when an older page is added above.
  useLayoutEffect(() => {
    const el = scrollRef.current
    const prev = shown.current
    const first = messages.length ? messages[0].id : null
    const olderAdded = prev.last !== null && first !== prev.first && lastId === prev.last
    if (olderAdded) el.scrollTop += el.scrollHeight - prev.height
    else if (prev.last === null || atBottomRef.current || (lastId !== prev.last && messages[messages.length - 1]?.mine)) {
      el.scrollTop = el.scrollHeight
      atBottomRef.current = true
      onAtBottomChange(true) // a remount scrolls to the bottom without a scroll event
    }
    shown.current = { first, last: lastId, height: el.scrollHeight }
  }, [messages, lastId, onAtBottomChange])

  const showPill = !atBottom && lastId !== null && lastId !== seenLast

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scrollRef}
        onScroll={onScroll}
        role="log"
        aria-live="polite"
        aria-label="Messages"
        tabIndex={0}
        className={`h-full space-y-3 overflow-y-auto overflow-x-hidden px-4 py-4 ${FOCUS}`}
      >
        {hasOlder && (
          <div className="flex justify-center">
            <button
              type="button"
              onClick={onLoadOlder}
              disabled={loadingOlder}
              className={`rounded-full border border-white/10 px-3 py-1 text-xs font-semibold text-zinc-300 hover:bg-white/[0.06] disabled:opacity-50 ${FOCUS}`}
            >
              {loadingOlder ? 'Loading...' : 'Load older messages'}
            </button>
          </div>
        )}
        {loading && messages.length === 0 && <p className="text-center text-xs text-zinc-500">Loading messages...</p>}
        {!loading && messages.length === 0 && (
          <p className="py-10 text-center text-sm text-zinc-500">No messages in this chat yet.</p>
        )}
        {messages.map((m, i) => {
          const separator = i === 0 || dayKeyIST(messages[i - 1].createdAt) !== dayKeyIST(m.createdAt)
          return (
            <Fragment key={m.id}>
              {separator && (
                <div className="flex justify-center">
                  <span className="rounded-full bg-white/[0.06] px-3 py-0.5 text-[11px] font-semibold text-zinc-400">
                    {formatIST(m.createdAt, DATE_ONLY)}
                  </span>
                </div>
              )}
              <MessageItem
                message={m}
                files={files}
                canEdit={m.canEdit && !expiredEdits.has(m.id) && canEditNow(m.editableUntil, offset, now)}
                editing={edit.id === m.id}
                edit={edit}
                onStartEdit={onStartEdit}
                onCancelEdit={onCancelEdit}
                onSaveEdit={onSaveEdit}
              />
            </Fragment>
          )
        })}
      </div>
      {showPill && (
        <button
          type="button"
          onClick={scrollToBottom}
          className={`absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-blue-600 px-3 py-1 text-xs font-bold text-white shadow-lg hover:bg-blue-500 ${FOCUS}`}
        >
          New messages
        </button>
      )}
    </div>
  )
}
