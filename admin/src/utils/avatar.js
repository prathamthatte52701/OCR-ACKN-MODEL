// The app has no profile photos: every user gets a coloured circle with initials. The colour is
// derived from the user id, so the same person always has the same colour.
const GRADIENTS = [
  'linear-gradient(135deg,#7c3aed,#6366f1)',
  'linear-gradient(135deg,#3b82f6,#06b6d4)',
  'linear-gradient(135deg,#14b8a6,#22c55e)',
  'linear-gradient(135deg,#f97316,#f59e0b)',
  'linear-gradient(135deg,#ec4899,#8b5cf6)',
  'linear-gradient(135deg,#6366f1,#3b82f6)',
]

export function avatarGradient(id = '') {
  let h = 0
  for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return GRADIENTS[h % GRADIENTS.length]
}

export function initialsOf(name = '') {
  const parts = String(name).trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '??'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}
