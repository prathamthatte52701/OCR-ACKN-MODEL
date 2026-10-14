// Small presentational pieces of the admin HUD theme (tokens live in index.css under .theme-admin).

import { HUD } from './hudColors'

// Circular gauge: `value` 0-100 drawn as an arc, big number in the centre.
export function Gauge({ value, label, color = HUD.green, size = 150, caption }) {
  const pct = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0))
  const r = 52
  const c = 2 * Math.PI * r
  return (
    <div className="flex flex-col items-center">
      <svg className="shrink-0" width={size} height={size} viewBox="0 0 140 140" role="img" aria-label={`${label}: ${pct}%`}>
        <circle cx="70" cy="70" r={r} fill="none" stroke="rgba(147,181,168,0.18)" strokeWidth="10" />
        <circle
          cx="70" cy="70" r={r} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round"
          strokeDasharray={`${(pct / 100) * c} ${c}`} transform="rotate(-90 70 70)"
          style={{ filter: `drop-shadow(0 0 6px ${color}88)` }}
        />
        <text x="70" y="68" textAnchor="middle" fontSize="28" fontWeight="800" fill="#e6f4ee">{pct}%</text>
        <text x="70" y="90" textAnchor="middle" fontSize="13" fill="#93b5a8">{label}</text>
      </svg>
      {caption && <p className="mt-1 text-[13px] text-[var(--hud-muted)]">{caption}</p>}
    </div>
  )
}

// Donut with the total in the centre. A single non-zero segment is drawn as one closed ring
// (no gap), several segments get small gaps between them.
export function Donut({ segments, total, size = 170, centerLabel = 'Documents' }) {
  const r = 56
  const c = 2 * Math.PI * r
  const live = segments.filter((s) => s.value > 0)
  const sum = live.reduce((a, s) => a + s.value, 0)
  const gap = live.length > 1 ? 4 : 0
  let offset = 0
  return (
    <svg className="shrink-0" width={size} height={size} viewBox="0 0 140 140" role="img" aria-label={`${centerLabel}: ${total}`}>
      <circle cx="70" cy="70" r={r} fill="none" stroke="rgba(147,181,168,0.18)" strokeWidth="14" />
      {sum > 0 && live.map((s) => {
        const len = (s.value / sum) * c
        const el = (
          <circle
            key={s.name} cx="70" cy="70" r={r} fill="none" stroke={s.color} strokeWidth="14"
            strokeDasharray={`${Math.max(len - gap, 0.5)} ${c}`} strokeDashoffset={-offset}
            transform="rotate(-90 70 70)"
          />
        )
        offset += len
        return el
      })}
      <text x="70" y="68" textAnchor="middle" fontSize="28" fontWeight="800" fill="#e6f4ee">{total}</text>
      <text x="70" y="88" textAnchor="middle" fontSize="13" fill="#93b5a8">{centerLabel}</text>
    </svg>
  )
}

export function Spinner() {
  return (
    <div className="flex justify-center py-16" role="status" aria-label="Loading">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-transparent border-t-[var(--hud-green)]" />
    </div>
  )
}
