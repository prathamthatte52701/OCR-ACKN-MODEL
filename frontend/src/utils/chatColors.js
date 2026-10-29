// The user's own bubble colour presets (ids match the backend's allowed colours).
export const CHAT_COLORS = [
  { id: 'blue', label: 'Blue', bubble: '#2563eb', text: '#ffffff' },
  { id: 'violet', label: 'Violet', bubble: '#7c3aed', text: '#ffffff' },
  { id: 'teal', label: 'Teal', bubble: '#0f766e', text: '#ffffff' },
  { id: 'green', label: 'Green', bubble: '#15803d', text: '#ffffff' },
  { id: 'amber', label: 'Amber', bubble: '#b45309', text: '#ffffff' },
  { id: 'orange', label: 'Orange', bubble: '#c2410c', text: '#ffffff' },
  { id: 'rose', label: 'Rose', bubble: '#e11d48', text: '#ffffff' },
  { id: 'slate', label: 'Slate', bubble: '#475569', text: '#ffffff' },
]

// Other people's messages.
export const NEUTRAL_BUBBLE = { bubble: '#27272a', text: '#f4f4f5' }

export function colorById(id) {
  return CHAT_COLORS.find((c) => c.id === id) ?? CHAT_COLORS[0]
}
