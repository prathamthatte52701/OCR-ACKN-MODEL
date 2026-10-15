// Small table helpers shared by the list pages (Documents, Workbooks, Activity, Orphaned files).
import { Avatar, Skeleton } from './ui'

// Avatar + username + email, both truncated with a title so long values never break the row.
export function OwnerCell({ owner, className = 'max-w-[240px]' }) {
  const name = owner?.username || 'unknown'
  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <Avatar id={owner?.id || owner?._id || owner?.email || name} name={name} size={34} />
      <div className="min-w-0">
        <div className="truncate font-semibold text-white" title={name}>{name}</div>
        {owner?.email && <div className="truncate text-[13px] text-[var(--muted)]" title={owner.email}>{owner.email}</div>}
      </div>
    </div>
  )
}

// Shimmer rows shown inside a card while a table loads.
export function TableSkeleton({ rows = 6 }) {
  return (
    <div className="space-y-3 p-4" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-11 w-full" />)}
    </div>
  )
}
