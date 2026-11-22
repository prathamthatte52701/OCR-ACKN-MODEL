import { PAGE_SIZE_OPTIONS } from '../hooks/usePageSize'

// "Entries per page" control shown at the bottom of every paged list (30 / 50 / 75 / 100).
export default function PageSizeSelect({ value, onChange }) {
  return (
    <div className="mt-4 flex items-center justify-center gap-2 text-[14px] font-semibold text-[var(--muted)]">
      <span>Entries per page</span>
      <select
        aria-label="Entries per page"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="input [color-scheme:dark] w-24"
      >
        {PAGE_SIZE_OPTIONS.map((n) => (
          <option key={n} value={n}>{n}</option>
        ))}
      </select>
    </div>
  )
}
