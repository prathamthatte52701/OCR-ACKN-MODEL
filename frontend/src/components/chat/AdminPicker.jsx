const STATE_TEXT = {
  loading: 'Loading admins...',
  error: 'Could not load the admin list.',
}

export default function AdminPicker({ admins, state, selectedId, onSelect }) {
  if (state !== 'ready') return <p className="px-4 text-xs text-zinc-400">{STATE_TEXT[state]}</p>
  if (admins.length === 0) return <p role="alert" className="px-4 text-xs text-amber-300">No admin is available right now.</p>
  const selected = admins.find((a) => a.id === selectedId)
  return (
    <div className="flex items-center gap-2 px-4 text-xs text-zinc-400">
      <label htmlFor="chat-admin" className="shrink-0">To admin ({selected?.name})</label>
      <select
        id="chat-admin"
        value={selectedId ?? ''}
        onChange={(e) => onSelect(e.target.value)}
        className="min-w-0 flex-1 truncate rounded-md border border-white/10 bg-zinc-900 px-2 py-1 text-xs text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
      >
        {admins.map((a) => (
          <option key={a.id} value={a.id}>{a.name}</option>
        ))}
      </select>
    </div>
  )
}
