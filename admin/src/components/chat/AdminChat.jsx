import { useAdminChat } from '../../hooks/useAdminChat'
import AdminChatPanel from './AdminChatPanel'

// Wires the chat hook to the panel. Always mounted (state survives closing the panel); the hook
// does no network work while `open` is false.
export default function AdminChat({ adminId, open, overlay, onClose, panelRef, byUser }) {
  const chat = useAdminChat({ adminId, open, byUser })

  return (
    <>
      {open && (
        <AdminChatPanel
          overlay={overlay}
          onClose={onClose}
          panelRef={panelRef}
          threads={chat.threads}
          threadsReady={chat.threadsReady}
          selected={chat.selectedThread}
          onSelect={chat.select}
          notice={chat.notice}
          list={{
            messages: chat.messages,
            offset: chat.offset,
            now: chat.now,
            expiredEdits: chat.expiredEdits,
            edit: chat.edit,
            onStartEdit: chat.startEdit,
            onCancelEdit: chat.cancelEdit,
            onSaveEdit: chat.saveEdit,
            hasOlder: chat.hasOlder,
            loadingOlder: chat.loadingOlder,
            onLoadOlder: chat.loadOlder,
            onAtBottomChange: chat.setAtBottom,
            loading: chat.loading,
          }}
          composer={{
            draft: chat.draft,
            onDraftChange: chat.setDraft,
            onSend: chat.send,
            sending: chat.sending,
            error: chat.sendError,
          }}
        />
      )}
    </>
  )
}
