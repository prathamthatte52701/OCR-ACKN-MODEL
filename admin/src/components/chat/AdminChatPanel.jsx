import Composer from './Composer'
import MessageList from './MessageList'
import UserPicker from './UserPicker'

const FOCUS = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#7c6cff]'

function Empty({ children }) {
  return <div className="grid min-h-0 flex-1 place-items-center px-6 text-center text-sm text-zinc-500">{children}</div>
}

// Presentational: data and callbacks arrive as props. `overlay` picks the dialog-with-backdrop
// layout (narrow screens); otherwise it is a docked complementary region.
export default function AdminChatPanel({
  overlay, onClose, panelRef, threads, threadsReady, selected, onSelect, notice, list, composer,
}) {
  const hasUser = Boolean(selected)
  let body = (
    <MessageList
      key={selected?.userId}
      messages={list.messages}
      offset={list.offset}
      now={list.now}
      expiredEdits={list.expiredEdits}
      edit={list.edit}
      onStartEdit={list.onStartEdit}
      onCancelEdit={list.onCancelEdit}
      onSaveEdit={list.onSaveEdit}
      hasOlder={list.hasOlder}
      loadingOlder={list.loadingOlder}
      onLoadOlder={list.onLoadOlder}
      onAtBottomChange={list.onAtBottomChange}
      loading={list.loading}
    />
  )
  if (!hasUser && notice) body = <Empty><p role="alert" className="text-amber-300">{notice}<br />Choose another user above.</p></Empty>
  else if (!hasUser && threadsReady && threads.length === 0) body = <Empty>No users to chat with yet.</Empty>
  else if (!hasUser) body = <Empty>{threadsReady ? 'Choose a user to start.' : 'Loading users...'}</Empty>

  const panel = (
    <section
      ref={panelRef}
      id="admin-chat-panel"
      role={overlay ? 'dialog' : 'complementary'}
      aria-modal={overlay ? 'true' : undefined}
      aria-label="Chat with users"
      tabIndex={-1}
      className={`flex flex-col border-l border-white/10 bg-[#0b0b0c] text-zinc-100 outline-none ${
        overlay ? 'relative h-full w-full max-w-[400px] shadow-2xl' : 'fixed bottom-0 right-0 top-16 z-20 w-[var(--chat-w)]'
      }`}
    >
      <header className="flex items-center gap-2 border-b border-white/10 px-3 py-3">
        <UserPicker threads={threads} selected={selected} onSelect={onSelect} />
        <button
          type="button"
          onClick={onClose}
          aria-label="Close chat"
          className={`shrink-0 rounded-lg border border-white/10 p-1.5 text-zinc-300 hover:bg-white/[0.06] ${FOCUS}`}
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true"><path strokeLinecap="round" d="M6 6l12 12M18 6 6 18" /></svg>
        </button>
      </header>
      {body}
      <Composer
        userName={selected?.name}
        draft={composer.draft}
        onDraftChange={composer.onDraftChange}
        onSend={composer.onSend}
        sending={composer.sending}
        error={composer.error}
        disabled={!hasUser}
      />
    </section>
  )

  if (!overlay) return panel
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button type="button" aria-hidden="true" tabIndex={-1} onClick={onClose} className="absolute inset-0 h-full w-full cursor-default bg-black/70" />
      {panel}
    </div>
  )
}
