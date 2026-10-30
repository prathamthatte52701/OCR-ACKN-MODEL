import { useEffect, useState } from 'react'
import { fileKind, formatBytes } from '../../utils/chatCore'

// The chosen file above the text box: thumbnail (image) or PDF icon, name, size, remove button.
export default function FileChip({ file, disabled, onRemove }) {
  const isImage = fileKind(file) === 'image'
  const [thumb, setThumb] = useState(null)
  useEffect(() => {
    if (!isImage) return undefined
    const url = URL.createObjectURL(file)
    const show = setTimeout(() => setThumb(url), 0)
    return () => {
      clearTimeout(show)
      URL.revokeObjectURL(url)
    }
  }, [file, isImage])
  return (
    <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-zinc-900 p-1.5">
      {isImage && thumb ? (
        <img src={thumb} alt="" className="h-10 w-10 shrink-0 rounded-md object-cover" />
      ) : (
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-white/[0.06] text-[10px] font-bold text-rose-300">PDF</span>
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-semibold text-zinc-100">{file.name}</p>
        <p className="text-[11px] text-zinc-400">{formatBytes(file.size)}</p>
      </div>
      <button
        type="button"
        onClick={onRemove}
        disabled={disabled}
        aria-label="Remove file"
        className="rounded-md p-1.5 text-zinc-300 hover:bg-white/[0.08] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#7c6cff] disabled:opacity-50"
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true"><path strokeLinecap="round" d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
    </div>
  )
}
