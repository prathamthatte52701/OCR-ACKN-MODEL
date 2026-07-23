import { useState } from 'react'
import useDialogStore from '../store/dialogStore'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from './ui/dialog'

// Keyed on promptState.id by the parent so each new prompt request remounts
// this form fresh - avoids a setState-in-effect resync when defaultValue
// changes between requests.
function PromptForm({ promptState, resolvePrompt }) {
  const [value, setValue] = useState(promptState.defaultValue || '')

  function handleSubmit() {
    const trimmed = value.trim()
    resolvePrompt(trimmed || null)
  }

  return (
    <DialogContent className="max-w-sm" showClose={false}>
      <DialogHeader>
        <DialogTitle>{promptState.title}</DialogTitle>
      </DialogHeader>
      <div className="space-y-3 px-5 py-4">
        {promptState.message && <p className="text-sm text-gray-300">{promptState.message}</p>}
        <input
          autoFocus
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder={promptState.placeholder}
          className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2.5 text-sm text-white outline-none transition-colors focus:border-blue-500"
        />
      </div>
      <DialogFooter>
        <button
          onClick={() => resolvePrompt(null)}
          className="rounded-lg bg-gray-800 px-4 py-2 text-sm text-gray-400 transition-colors hover:bg-gray-700 hover:text-gray-200"
        >
          Cancel
        </button>
        <button
          onClick={handleSubmit}
          disabled={!value.trim()}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          OK
        </button>
      </DialogFooter>
    </DialogContent>
  )
}

// Mounted once in App.jsx - renders whenever promptText() from
// store/dialogStore is called anywhere in the app (replaces window.prompt(),
// used for naming a new Excel workbook).
export default function GlobalPromptDialog() {
  const promptState = useDialogStore((s) => s.promptState)
  const resolvePrompt = useDialogStore((s) => s.resolvePrompt)
  const open = Boolean(promptState)

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) resolvePrompt(null) }}>
      {open && <PromptForm key={promptState.id} promptState={promptState} resolvePrompt={resolvePrompt} />}
    </Dialog>
  )
}
