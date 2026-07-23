import { useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from './ui/dialog'

export default function CorrectionModal({ field, onSave, onClose }) {
  const [value, setValue] = useState(field?.value ?? '')
  const [saving, setSaving] = useState(false)

  if (!field) return null

  async function handleSave() {
    if (!value.trim()) return
    setSaving(true)
    await onSave(field, value.trim())
    setSaving(false)
  }

  return (
    <Dialog open onOpenChange={(next) => { if (!next) onClose() }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Edit Field Value</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 px-5 py-5">
          <div>
            <p className="mb-1 text-xs text-gray-500">Field</p>
            <p className="font-medium text-gray-200">{field.label}</p>
          </div>
          <div>
            <p className="mb-1 text-xs text-gray-500">Original Value</p>
            <p className="font-mono text-sm text-gray-400">{field.value || 'N/A'}</p>
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-500">New Value</label>
            <input
              type="text"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2.5 text-sm text-white outline-none transition-colors focus:border-blue-500"
              placeholder="Enter corrected value"
              autoFocus
              onKeyDown={(e) => e.key === 'Enter' && handleSave()}
            />
          </div>
        </div>

        <DialogFooter>
          <button
            onClick={onClose}
            className="rounded-lg bg-gray-800 px-4 py-2 text-sm text-gray-400 transition-colors hover:bg-gray-700 hover:text-gray-200"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !value.trim()}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Correction'}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
