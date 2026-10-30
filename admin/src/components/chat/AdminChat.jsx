import { useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import { useAdminChat } from '../../hooks/useAdminChat'
import AdminChatPanel from './AdminChatPanel'
import ClearChatModal from './ClearChatModal'

// Wires the chat hook to the panel. Always mounted (state survives closing the panel); the hook
// does no network work while `open` is false. The clear dialog sits outside the panel so it is
// never trapped under the panel's stacking context.
export default function AdminChat({ adminId, open, overlay, onClose, panelRef, byUser }) {
  const chat = useAdminChat({ adminId, open, byUser })
  const [clearing, setClearing] = useState(false)

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
          onClear={() => setClearing(true)}
          list={{
            messages: chat.messages,
            offset: chat.offset,
            now: chat.now,
            files: chat.files,
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
            file: chat.file,
            onFileChange: chat.chooseFile,
            fileError: chat.fileError,
            progress: chat.progress,
          }}
        />
      )}
      <AnimatePresence>
        {open && clearing && chat.selectedThread && (
          <ClearChatModal user={chat.selectedThread} onClose={() => setClearing(false)} onCleared={chat.reloadThread} />
        )}
      </AnimatePresence>
    </>
  )
}
