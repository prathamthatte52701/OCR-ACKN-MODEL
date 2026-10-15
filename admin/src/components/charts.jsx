// Hand-built SVG charts (no chart library): light, themeable, and they handle tiny/empty data.
import { useId } from 'react'
import { PALETTE } from '../utils/palette'

function points(values, w, h, pad = 3) {
  const max = Math.max(1, ...values)
  const step = values.length > 1 ? (w - pad * 2) / (values.length - 1) : 0
  return values.map((v, i) => [pad + i * step, h - pad - (v / max) * (h - pad * 2)])
}

// Tiny trend line for stat cards. Needs at least 2 points and some non-zero value, else nothing.
export function Sparkline({ values = [], color = PALETTE.violetSoft, width = 130, height = 44, className = '' }) {
  const gid = useId()
  if (values.length < 2 || Math.max(...values) <= 0) return null
  const pts = points(values, width, height)
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  const area = `${line} L${pts[pts.length - 1][0].toFixed(1)},${height} L${pts[0][0].toFixed(1)},${height} Z`
  const last = pts[pts.length - 1]
  return (
    <svg className={className} width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.4" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r="3" fill="#fff" />
    </svg>
  )
}

// Larger glowing area/line chart with a y grid and a few date labels.
export function AreaChart({ days = [], values = [], color = PALETTE.violetSoft, height = 220, label = 'Documents per day' }) {
  const gid = useId()
  const w = 640
  const h = height
  const padL = 36
  const padB = 24
  const padT = 10
  const total = values.reduce((a, b) => a + b, 0)
  if (values.length < 2 || total === 0) {
    return <div className="grid place-items-center text-[14px] text-[var(--muted)]" style={{ height }}>No documents in this period yet</div>
  }
  const max = Math.max(1, ...values)
  const niceMax = Math.max(4, Math.ceil(max / 4) * 4)
  const step = (w - padL - 8) / (values.length - 1)
  const y = (v) => padT + (1 - v / niceMax) * (h - padT - padB)
  const pts = values.map((v, i) => [padL + i * step, y(v)])
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
  const area = `${line} L${pts[pts.length - 1][0].toFixed(1)},${h - padB} L${pts[0][0].toFixed(1)},${h - padB} Z`
  const ticks = [0, 1, 2, 3, 4].map((i) => (niceMax / 4) * i)
  const last = values.length - 1
  const labelIdx = [0, Math.floor(last / 3), Math.floor((last * 2) / 3), last]
  const fmt = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', timeZone: 'UTC' })
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img" aria-label={label} preserveAspectRatio="none" style={{ display: 'block' }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.45" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={padL} x2={w - 8} y1={y(t)} y2={y(t)} stroke="rgba(148,156,230,0.14)" strokeDasharray="3 4" />
          <text x={padL - 8} y={y(t) + 4} textAnchor="end" fontSize="13" fill="#a3abdc">{t}</text>
        </g>
      ))}
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" style={{ filter: `drop-shadow(0 0 6px ${color})` }} />
      {pts.map((p, i) => (values[i] > 0 && (i === last || values.length <= 16)) && <circle key={i} cx={p[0]} cy={p[1]} r="3.5" fill="#fff" stroke={color} strokeWidth="2" />)}
      {labelIdx.map((i) => days[i] && <text key={i} x={pts[i][0]} y={h - 6} textAnchor={i === 0 ? 'start' : i === last ? 'end' : 'middle'} fontSize="13" fill="#a3abdc">{fmt(days[i])}</text>)}
    </svg>
  )
}

// Donut with the total in the middle. One non-zero segment = one closed ring (no gap).
export function Donut({ segments = [], total = 0, size = 170, centerLabel = 'Total', thickness = 15 }) {
  const r = 56
  const c = 2 * Math.PI * r
  const live = segments.filter((s) => s.value > 0)
  const sum = live.reduce((a, s) => a + s.value, 0)
  const gap = live.length > 1 ? 5 : 0
  let offset = 0
  return (
    <svg className="shrink-0" width={size} height={size} viewBox="0 0 140 140" role="img" aria-label={`${centerLabel}: ${total}`}>
      <circle cx="70" cy="70" r={r} fill="none" stroke="rgba(148,156,230,0.14)" strokeWidth={thickness} />
      {sum > 0 && live.map((s) => {
        const len = (s.value / sum) * c
        const el = (
          <circle key={s.name} cx="70" cy="70" r={r} fill="none" stroke={s.color} strokeWidth={thickness}
            strokeDasharray={`${Math.max(len - gap, 0.5)} ${c}`} strokeDashoffset={-offset} transform="rotate(-90 70 70)" />
        )
        offset += len
        return el
      })}
      <text x="70" y="68" textAnchor="middle" fontSize="23" fontWeight="800" fill="#f1f3ff">{total}</text>
      <text x="70" y="87" textAnchor="middle" fontSize="12.5" fill="#a3abdc">{centerLabel}</text>
    </svg>
  )
}

// Half-circle multi-colour gauge for a 0-100 value (red, amber, teal, violet).
export function Gauge({ value = 0, label = '', width = 230 }) {
  const gid = useId()
  const pct = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0))
  const cx = 110
  const cy = 105
  const r = 82
  const arc = (from, to) => {
    const a = (p) => Math.PI * (1 - p / 100)
    const x1 = cx + r * Math.cos(a(from))
    const y1 = cy - r * Math.sin(a(from))
    const x2 = cx + r * Math.cos(a(to))
    const y2 = cy - r * Math.sin(a(to))
    return `M${x1.toFixed(1)},${y1.toFixed(1)} A${r},${r} 0 0 1 ${x2.toFixed(1)},${y2.toFixed(1)}`
  }
  return (
    <svg width={width} height={width * 0.62} viewBox="0 0 220 135" role="img" aria-label={`${label}: ${pct}%`}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor={PALETTE.red} />
          <stop offset="30%" stopColor={PALETTE.amber} />
          <stop offset="65%" stopColor={PALETTE.teal} />
          <stop offset="100%" stopColor={PALETTE.violet} />
        </linearGradient>
      </defs>
      <path d={arc(0, 99.99)} fill="none" stroke="rgba(148,156,230,0.16)" strokeWidth="16" strokeLinecap="round" />
      {pct > 0 && <path d={arc(0, Math.min(pct, 99.99))} fill="none" stroke={`url(#${gid})`} strokeWidth="16" strokeLinecap="round" />}
      <text x="110" y="92" textAnchor="middle" fontSize="32" fontWeight="800" fill="#f1f3ff">{pct}%</text>
      <text x="110" y="114" textAnchor="middle" fontSize="13" fill="#a3abdc">{label}</text>
      <text x="22" y="130" textAnchor="middle" fontSize="12.5" fill="#a3abdc">0%</text>
      <text x="198" y="130" textAnchor="middle" fontSize="12.5" fill="#a3abdc">100%</text>
    </svg>
  )
}
