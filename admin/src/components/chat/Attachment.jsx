import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import { formatBytes } from '../../utils/chatCore'

const FOCUS = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#7c6cff]'
const BTN = `rounded-md border border-white/15 px-2.5 py-1 text-xs font-semibold text-zinc-200 hover:bg-white/[0.08] ${FOCUS}`

function Muted({ children }) {
  return <p className="rounded-2xl bg-white/[0.04] px-3 py-2 text-xs italic text-zinc-500">{children}</p>
}

// Full-size image over the page: focus is trapped inside, Escape closes, and focus goes back to the
// thumbnail that opened it (useFocusTrap restores the previously focused element).
function ImageViewer({ url, name, onClose }) {
  const ref = useRef(null)
  useFocusTrap(ref)
  return createPortal(
    <div
      ref={ref}
      role="dialog"
      aria-modal="true"
      aria-label={name}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation()
          onClose()
        }
      }}
      onClick={onClose}
      className="fixed inset-0 z-[90] flex flex-col items-center justify-center gap-3 bg-black/90 p-4"
    >
      <button type="button" onClick={onClose} aria-label="Close image" className={`absolute right-4 top-4 ${BTN}`}>
        Close
      </button>
      <img src={url} alt={name} onClick={(e) => e.stopPropagation()} className="max-h-[85vh] max-w-full object-contain" />
      <p className="max-w-full truncate text-xs text-zinc-300">{name}</p>
    </div>,
    document.querySelector('.theme-admin') ?? document.body,
  )
}

function save(url, name) {
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
}

// One attachment inside a message. The file is fetched only once its message is near the viewport.
export default function Attachment({ att, files }) {
  const boxRef = useRef(null)
  const [viewer, setViewer] = useState(false)
  const entry = files.get(att.id)

  useEffect(() => {
    if (att.expired || files.get(att.id)) return undefined
    if (typeof IntersectionObserver === 'undefined') {
      files.request(att.id)
      return undefined
    }
    const io = new IntersectionObserver(
      ([hit]) => {
        if (hit.isIntersecting) {
          files.request(att.id)
          io.disconnect()
        }
      },
      { rootMargin: '200px' },
    )
    io.observe(boxRef.current)
    return () => io.disconnect()
  }, [att.id, att.expired, files])

  if (att.expired || entry?.state === 'expired') return <Muted>File expired</Muted>
  if (entry?.state === 'missing') return <Muted>File not available</Muted>

  if (att.kind === 'image') {
    return (
      <div ref={boxRef} className="h-40 w-60 max-w-full overflow-hidden rounded-2xl bg-white/[0.06]">
        {entry?.state === 'ready' && (
          <>
            <button type="button" onClick={() => setViewer(true)} aria-label={`Open image ${att.name}`} className={`block h-full w-full ${FOCUS}`}>
              <img src={entry.url} alt={att.name} className="h-full w-full object-contain" />
            </button>
            {viewer && <ImageViewer url={entry.url} name={att.name} onClose={() => setViewer(false)} />}
          </>
        )}
      </div>
    )
  }

  const ready = entry?.state === 'ready'
  return (
    <div ref={boxRef} className="flex max-w-[85%] items-center gap-3 rounded-2xl bg-white/[0.06] px-3 py-2">
      <svg className="h-8 w-8 shrink-0 text-rose-300" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 24 24" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5" />
      </svg>
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-zinc-100">{att.name}</p>
        <p className="text-xs text-zinc-400">PDF - {formatBytes(att.size)}</p>
        <div className="mt-1.5 flex gap-2">
          <button type="button" disabled={!ready} onClick={() => window.open(entry.url, '_blank', 'noopener,noreferrer')} className={`${BTN} disabled:opacity-50`}>
            {ready ? 'Open' : 'Loading...'}
          </button>
          <button type="button" disabled={!ready} onClick={() => save(entry.url, att.name)} className={`${BTN} disabled:opacity-50`}>
            Download
          </button>
        </div>
      </div>
    </div>
  )
}
