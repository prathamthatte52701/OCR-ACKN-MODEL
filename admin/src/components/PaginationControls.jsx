// Mirrors the Previous/Next + "Page X of Y" pattern used on the main app's
// My Documents page.
export default function PaginationControls({ page, totalPages, onChange }) {
  if (totalPages <= 1) return null

  return (
    <div className="mt-6 flex items-center justify-center gap-4">
      <button
        onClick={() => onChange(Math.max(1, page - 1))}
        disabled={page <= 1}
        className="inline-flex items-center justify-center rounded-2xl border border-white/10 bg-white/[0.045] px-5 py-2.5 text-[13.6px] font-bold text-slate-200 transition-colors hover:border-emerald-300/30 hover:bg-emerald-500/10 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-white/10 disabled:hover:bg-white/[0.045]"
      >
        Previous
      </button>
      <span className="text-[13.6px] font-bold text-slate-400">
        Page {page} of {totalPages}
      </span>
      <button
        onClick={() => onChange(Math.min(totalPages, page + 1))}
        disabled={page >= totalPages}
        className="inline-flex items-center justify-center rounded-2xl border border-white/10 bg-white/[0.045] px-5 py-2.5 text-[13.6px] font-bold text-slate-200 transition-colors hover:border-emerald-300/30 hover:bg-emerald-500/10 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-white/10 disabled:hover:bg-white/[0.045]"
      >
        Next
      </button>
    </div>
  )
}
