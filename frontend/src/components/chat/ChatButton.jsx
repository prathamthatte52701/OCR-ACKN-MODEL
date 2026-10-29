import { MessageSquare } from 'lucide-react'

export default function ChatButton({ unread, open, onClick, buttonRef }) {
  const badge = unread > 9 ? '9+' : String(unread)
  const label = `${open ? 'Close' : 'Open'} chat${unread > 0 ? `, ${unread} unread` : ''}`
  return (
    <button
      ref={buttonRef}
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-expanded={open}
      className="relative flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-2 text-[12.6px] font-bold text-slate-300 transition-colors hover:border-blue-300/30 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 motion-reduce:transition-none sm:px-3"
    >
      <MessageSquare className="h-4 w-4" aria-hidden="true" />
      <span className="hidden sm:inline">Chat</span>
      {unread > 0 && (
        <span
          aria-hidden="true"
          className="absolute -right-1.5 -top-1.5 grid h-5 min-w-5 place-items-center rounded-full bg-rose-600 px-1 text-[11px] font-bold leading-none text-white ring-2 ring-[#020817]"
        >
          {badge}
        </span>
      )}
    </button>
  )
}
