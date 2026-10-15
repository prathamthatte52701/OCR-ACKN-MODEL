// Mirrors the Previous/Next + "Page X of Y" pattern used on the main app's
// My Documents page.
export default function PaginationControls({ page, totalPages, onChange }) {
  if (totalPages <= 1) return null

  return (
    <div className="mt-6 flex items-center justify-center gap-4">
      <button
        onClick={() => onChange(Math.max(1, page - 1))}
        disabled={page <= 1}
        className="btn btn-ghost"
      >
        Previous
      </button>
      <span className="text-[14px] font-semibold text-[var(--muted)]">
        Page {page} of {totalPages}
      </span>
      <button
        onClick={() => onChange(Math.min(totalPages, page + 1))}
        disabled={page >= totalPages}
        className="btn btn-ghost"
      >
        Next
      </button>
    </div>
  )
}
