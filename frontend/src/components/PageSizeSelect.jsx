import { PAGE_SIZE_OPTIONS } from '../hooks/usePageSize'

const selectClass = 'rounded-2xl border border-white/10 bg-slate-900 px-3 py-2 text-[13.6px] font-bold text-slate-200 focus:border-blue-300/40 focus:outline-none'

// "Entries per page" control shown at the bottom of every paged list (30 / 50 / 75 / 100).
export default function PageSizeSelect({ value, onChange }) {
  return (
    <div className="mt-6 flex items-center justify-center gap-2 text-[13.6px] font-medium text-slate-500">
      <span>Entries per page</span>
      <select
        aria-label="Entries per page"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className={selectClass}
      >
        {PAGE_SIZE_OPTIONS.map((n) => (
          <option key={n} value={n}>{n}</option>
        ))}
      </select>
    </div>
  )
}
