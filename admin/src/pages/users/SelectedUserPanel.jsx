import { Link } from 'react-router-dom'
import { Avatar, Badge, Card, Skeleton } from '../../components/ui'
import { statusTone } from '../../utils/status'
import { formatIST, formatISTDate } from '../../utils/formatDate'

const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '')

function Tile({ label, children }) {
  return (
    <div className="ui-card ui-card-flat min-w-0 p-4">
      <div className="truncate text-[18px] font-bold text-white">{children}</div>
      <div className="mt-0.5 text-[13px] text-[var(--muted)]">{label}</div>
    </div>
  )
}

function Row({ label, children }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-[var(--line-soft)] py-3 last:border-0">
      <dt className="text-[14px] text-[var(--muted)]">{label}</dt>
      <dd className="min-w-0 break-words text-right text-[14px] font-semibold text-white">{children}</dd>
    </div>
  )
}

// Right-hand "Selected user" card. `user` is the list row (fresh after every reload);
// `detail` is GET /admin/users/{id} (documentCount, lastActiveAt) or null while loading.
export default function SelectedUserPanel({ user, detail, detailLoading, busy, onApprove, onReject }) {
  if (!user) {
    return (
      <Card className="hidden p-5 xl:block" aria-label="Selected user">
        <h2 className="text-[18px] font-bold text-white">Selected user</h2>
        <p className="mt-3 text-[14px] text-[var(--muted)]">Select a user in the table to see their details.</p>
      </Card>
    )
  }
  const docs = detail?.documentCount ?? user.documentCount
  const lastActive = detail?.lastActiveAt
  return (
    <Card className="p-5" aria-label="Selected user">
      <h2 className="mb-4 text-[18px] font-bold text-white">Selected user</h2>
      <div className="flex items-center gap-4">
        <Avatar id={user.id} name={user.username} size={64} />
        <div className="min-w-0">
          <div className="truncate text-[20px] font-bold text-white" title={user.username}>{user.username}</div>
          <div className="truncate text-[14px] text-[var(--violet-2)]" title={user.email}>{user.email}</div>
          <div className="mt-2"><Badge tone={statusTone(user.status)} dot>{cap(user.status)}</Badge></div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3">
        <Tile label="Documents">{detailLoading && docs == null ? <Skeleton className="h-6 w-12" /> : (docs ?? '-')}</Tile>
        <Tile label="Joined">{formatISTDate(user.createdAt)}</Tile>
      </div>

      <h3 className="mb-1 mt-6 text-[16px] font-bold text-white">Account details</h3>
      <dl>
        <Row label="Role">{cap(user.role)}</Row>
        {lastActive && <Row label="Last active">{formatIST(lastActive)}</Row>}
        {user.decidedAt && <Row label="Decision">{cap(user.decision)} {formatISTDate(user.decidedAt)}</Row>}
        {user.decisionReason && <Row label="Reason">{user.decisionReason}</Row>}
      </dl>

      <Link to={`/users/${user.id}`} className="btn btn-ghost btn-sm mt-4 w-full">View activity</Link>

      {user.status === 'pending' && (
        <div className="mt-5 border-t border-[var(--line-soft)] pt-5">
          <h3 className="text-[16px] font-bold text-white">Review request</h3>
          <p className="mt-1 text-[14px] text-[var(--muted)]">New account awaiting admin approval.</p>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <button type="button" disabled={busy} onClick={() => onApprove(user)} className="btn btn-success">Approve user</button>
            <button type="button" disabled={busy} onClick={() => onReject(user)} className="btn btn-danger">Reject</button>
          </div>
        </div>
      )}
    </Card>
  )
}
