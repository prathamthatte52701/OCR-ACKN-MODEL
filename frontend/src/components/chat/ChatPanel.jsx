import { useRef, useState } from 'react'
import { Palette, X } from 'lucide-react'
import ColorPicker from './ColorPicker'
import Composer from './Composer'
import MessageList from './MessageList'

const FOCUS = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400'

// Presentational: data and callbacks arrive as props. `overlay` picks the dialog-with-backdrop
// layout (narrow screens); otherwise it is a docked complementary region.
export default function ChatPanel({ overlay, onClose, panelRef, color, onColorChange, colorFailed, onInsertSummary, ...rest }) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const composerRef = useRef(null)

  async function insertSummary() {
    await onInsertSummary()
    composerRef.current?.focus()
  }

  const panel = (
    <section
      ref={panelRef}
      id="chat-panel"
      role={overlay ? 'dialog' : 'complementary'}
      aria-modal={overlay ? 'true' : undefined}
      aria-label="Chat with admin"
      tabIndex={-1}
      className={`flex flex-col border-l border-white/10 bg-[#0b0b0c] text-zinc-100 outline-none ${
        overlay
          ? 'relative h-full w-full max-w-[400px] shadow-2xl'
          : 'fixed bottom-0 right-0 top-16 z-40 w-[var(--chat-w)]'
      }`}
    >
      <header className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
        <h2 className="mr-auto text-sm font-bold">Chat with admin</h2>
        <button
          type="button"
          onClick={() => setPickerOpen((o) => !o)}
          aria-label="Change message colour"
          aria-expanded={pickerOpen}
          className={`rounded-lg border border-white/10 p-1.5 text-zinc-300 hover:bg-white/[0.06] ${FOCUS}`}
        >
          <Palette className="h-4 w-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close chat"
          className={`rounded-lg border border-white/10 p-1.5 text-zinc-300 hover:bg-white/[0.06] ${FOCUS}`}
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </header>
      {pickerOpen && (
        <ColorPicker
          value={color.id}
          failed={colorFailed}
          onChange={(id) => {
            onColorChange(id)
            setPickerOpen(false)
          }}
        />
      )}
      <MessageList
        color={color}
        messages={rest.messages}
        offset={rest.offset}
        now={rest.now}
        expiredEdits={rest.expiredEdits}
        edit={rest.edit}
        onStartEdit={rest.onStartEdit}
        onCancelEdit={rest.onCancelEdit}
        onSaveEdit={rest.onSaveEdit}
        hasOlder={rest.hasOlder}
        loadingOlder={rest.loadingOlder}
        onLoadOlder={rest.onLoadOlder}
        onAtBottomChange={rest.onAtBottomChange}
        loading={rest.loading}
      />
      <Composer
        textareaRef={composerRef}
        draft={rest.draft}
        onDraftChange={rest.onDraftChange}
        onSend={rest.onSend}
        sending={rest.sending}
        error={rest.sendError}
        admins={rest.admins}
        adminsState={rest.adminsState}
        selectedAdminId={rest.selectedAdminId}
        onSelectAdmin={rest.onSelectAdmin}
        onInsertSummary={insertSummary}
        summaryError={rest.summaryError}
      />
    </section>
  )

  if (!overlay) return panel
  return (
    <div className="fixed inset-0 z-[60] flex justify-end">
      <button type="button" aria-hidden="true" tabIndex={-1} onClick={onClose} className="absolute inset-0 h-full w-full cursor-default bg-black/60" />
      {panel}
    </div>
  )
}
