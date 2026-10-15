import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'

const MENU_W = 192
const ITEM_H = 38

const itemCls = (danger) =>
  `flex w-full items-center rounded-lg px-3 py-2 text-left text-[14px] font-semibold no-underline disabled:cursor-not-allowed disabled:opacity-45 ${danger ? 'text-rose-300 hover:bg-rose-500/10' : 'text-white hover:bg-white/10'}`

// "..." row menu. The popover is portalled into the admin theme root and positioned with
// `fixed`, so the table's horizontal scroll container can never clip it.
// items: [{ key, label, to?, onClick?, disabled?, title?, danger? }]
export default function RowMenu({ label, items }) {
  const [pos, setPos] = useState(null) // null = closed
  const btnRef = useRef(null)
  const menuRef = useRef(null)
  const open = pos !== null

  const close = useCallback((refocus) => {
    setPos(null)
    if (refocus) btnRef.current?.focus()
  }, [])

  function toggle() {
    if (open) { close(false); return }
    const r = btnRef.current.getBoundingClientRect()
    const h = items.length * ITEM_H + 12
    const top = r.bottom + 4 + h > window.innerHeight ? Math.max(8, r.top - 4 - h) : r.bottom + 4
    setPos({ top, left: Math.max(8, r.right - MENU_W), root: btnRef.current.closest('.theme-admin') || document.body })
  }

  useEffect(() => {
    if (!open) return undefined
    menuRef.current?.querySelector('[role="menuitem"]:not([disabled])')?.focus()
    const onDown = (e) => {
      if (!menuRef.current?.contains(e.target) && !btnRef.current?.contains(e.target)) close(false)
    }
    const onKey = (e) => { if (e.key === 'Escape') close(true) }
    const away = () => close(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('resize', away)
    window.addEventListener('scroll', away, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', away)
      window.removeEventListener('scroll', away, true)
    }
  }, [open, close])

  function onMenuKeyDown(e) {
    if (e.key === 'Tab') { close(false); return }
    const els = [...menuRef.current.querySelectorAll('[role="menuitem"]:not([disabled])')]
    if (!els.length) return
    const i = els.indexOf(document.activeElement)
    let next = null
    if (e.key === 'ArrowDown') next = els[(i + 1) % els.length]
    else if (e.key === 'ArrowUp') next = els[(i - 1 + els.length) % els.length]
    else if (e.key === 'Home') next = els[0]
    else if (e.key === 'End') next = els[els.length - 1]
    if (next) { e.preventDefault(); next.focus() }
  }

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={toggle}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        className="btn btn-ghost btn-sm !min-h-[34px] !px-2"
      >
        <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg>
      </button>
      {open && createPortal(
        <div
          ref={menuRef}
          role="menu"
          aria-label={label}
          onKeyDown={onMenuKeyDown}
          style={{ position: 'fixed', top: pos.top, left: pos.left, width: MENU_W }}
          className="ui-card z-50 bg-[var(--surface-solid)] p-1.5"
        >
          {items.map((it) => it.to ? (
            <Link key={it.key} role="menuitem" to={it.to} onClick={() => close(false)} className={itemCls(it.danger)}>{it.label}</Link>
          ) : (
            <button
              key={it.key}
              type="button"
              role="menuitem"
              disabled={it.disabled}
              title={it.title}
              onClick={() => { close(false); it.onClick?.() }}
              className={itemCls(it.danger)}
            >
              {it.label}
            </button>
          ))}
        </div>,
        pos.root,
      )}
    </>
  )
}
