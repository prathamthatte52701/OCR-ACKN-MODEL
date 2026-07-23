import { create } from 'zustand'

// Backs two app-wide async dialogs (GlobalConfirmDialog / GlobalPromptDialog)
// that replace window.confirm()/window.prompt() with the styled shadcn-style
// Dialog, while keeping the same "await it like a function" call shape the
// old code used - so ported logic (e.g. saveDocument()'s workbook-creation
// retry) barely changes.
const useDialogStore = create((set) => ({
  confirmState: null,
  promptState: null,
  requestConfirm(options) {
    return new Promise((resolve) => {
      set({ confirmState: { ...options, resolve } })
    })
  },
  requestPrompt(options) {
    return new Promise((resolve) => {
      // A per-request id lets GlobalPromptDialog key its form on it, so a new
      // prompt's defaultValue seeds initial state via useState directly
      // instead of a setState-in-effect resync.
      set({ promptState: { ...options, id: `${Date.now()}-${Math.random()}`, resolve } })
    })
  },
  resolveConfirm(value) {
    set((state) => {
      state.confirmState?.resolve(value)
      return { confirmState: null }
    })
  },
  resolvePrompt(value) {
    set((state) => {
      state.promptState?.resolve(value)
      return { promptState: null }
    })
  },
}))

export function confirmAction({ title = 'Are you sure?', message, confirmLabel = 'Confirm', danger = false } = {}) {
  return useDialogStore.getState().requestConfirm({ title, message, confirmLabel, danger })
}

export function promptText({ title, message, defaultValue = '', placeholder = '' } = {}) {
  return useDialogStore.getState().requestPrompt({ title, message, defaultValue, placeholder })
}

export default useDialogStore
