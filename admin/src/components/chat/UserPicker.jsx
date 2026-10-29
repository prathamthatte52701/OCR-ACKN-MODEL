import { useEffect, useId, useRef, useState } from 'react'
import { SEARCH_FROM, badgeText, filterThreads } from '../../utils/chatAdminCore'

const FOCUS = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#7c6cff]'

function UnreadDot({ count }) {
  const text = badgeText(count)
  if (!text) return null
  return (
    <span aria-label={`${count} unread`} className="grid h-5 min-w-5 shrink-0 place-items-center rounded-full bg-rose-500 px-1 text-[11px] font-bold leading-none text-white">
      {text}
    </span>
  )
}

// Accessible listbox in a popup: Arrow keys move, Enter picks, Escape closes. Shows a search box
// when there are many users. Unread counts arrive already merged by the caller.
export default function UserPicker({ threads, selected, onSelect }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const rootRef = useRef(null)
  const buttonRef = useRef(null)
  const searchRef = useRef(null)
  const listRef = useRef(null)
  const listId = useId()
  const searchable = threads.length > SEARCH_FROM
  const shown = filterThreads(threads, query)

  useEffect(() => {
    if (!open) return undefined
    const target = searchRef.current ?? listRef.current
    target?.focus()
    function onDown(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  // keep the arrowed-to option in view
  const activeId = shown[active]?.userId
  useEffect(() => {
    if (open && activeId) document.getElementById(`${listId}-${activeId}`)?.scrollIntoView({ block: 'nearest' })
  }, [open, activeId, listId])

  function close() {
    setOpen(false)
    buttonRef.current?.focus()
  }

  function pick(thread) {
    onSelect(thread.userId)
    close()
  }

  function onKeyDown(e) {
    if (e.key === 'Escape') {
      e.stopPropagation()
      close()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => Math.min(i + 1, shown.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && shown[active]) {
      e.preventDefault()
      pick(shown[active])
    }
  }

  return (
    <div ref={rootRef} className="relative min-w-0 flex-1">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={selected ? `Chat with ${selected.name}. Choose another user` : 'Choose a user'}
        onClick={() => {
          setQuery('')
          setActive(Math.max(0, threads.findIndex((t) => t.userId === selected?.userId)))
          setOpen((o) => !o)
        }}
        className={`flex w-full items-center gap-2 rounded-lg border border-white/10 bg-zinc-900 px-2.5 py-1.5 text-left text-sm font-bold text-zinc-100 hover:bg-zinc-800 ${FOCUS}`}
      >
        <span className="min-w-0 flex-1 truncate">{selected ? selected.name : 'Choose a user'}</span>
        {selected && <UnreadDot count={selected.unreadCount} />}
        <svg className="h-4 w-4 shrink-0 text-zinc-400" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      {open && (
        <div
          onKeyDown={onKeyDown}
          onBlur={(e) => { if (!rootRef.current.contains(e.relatedTarget)) setOpen(false) }}
          className="absolute left-0 right-0 top-full z-10 mt-1 overflow-hidden rounded-xl border border-white/10 bg-[#111113] shadow-2xl">
          {searchable && (
            <input
              ref={searchRef}
              type="search"
              value={query}
              onChange={(e) => { setQuery(e.target.value); setActive(0) }}
              aria-label="Search users"
              aria-controls={listId}
              placeholder="Search users"
              className={`block w-full border-b border-white/10 bg-transparent px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 ${FOCUS}`}
            />
          )}
          <ul
            ref={listRef}
            id={listId}
            role="listbox"
            tabIndex={-1}
            aria-label="Users"
            aria-activedescendant={shown[active] ? `${listId}-${shown[active].userId}` : undefined}
            className={`m-0 max-h-64 list-none overflow-y-auto p-1 ${FOCUS}`}
          >
            {shown.length === 0 && <li className="px-3 py-2 text-xs text-zinc-500">No users match.</li>}
            {shown.map((t, i) => (
              <li
                key={t.userId}
                id={`${listId}-${t.userId}`}
                role="option"
                aria-selected={t.userId === selected?.userId}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(t)}
                onMouseMove={() => setActive(i)}
                className={`flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-zinc-100 ${i === active ? 'bg-white/10' : ''} ${t.userId === selected?.userId ? 'font-bold' : ''}`}
              >
                <span className="min-w-0 flex-1 truncate">{t.name}</span>
                <UnreadDot count={t.unreadCount} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
