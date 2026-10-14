import { useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import api from '../utils/api'
import Banner from '../components/Banner'
import BackButton from '../components/BackButton'
import ConfirmPurgeModal from '../components/ConfirmPurgeModal'

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

function WarningIcon({ className = 'h-4 w-4' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  )
}

function purgeGlobalRange(body) {
  return api.delete('/admin/purge-range', { data: body }).then((res) => res.data)
}

function purgeGlobalMonths(body) {
  return api.delete('/admin/purge-months', { data: body }).then((res) => res.data)
}

// Two selectable modes, both ALWAYS applied across every user's data: (a)
// age-based oldest-first (1/2/3/6/9 months), (b) exact year + specific
// month(s). Distinct concepts offered side by side, not merged - reuses the
// same confirmation gate/rate limit/surgical row-removal mechanism as the
// per-user "Nuke This User" action on the user detail page.
function GlobalNukePanel() {
  const [mode, setMode] = useState('age')
  const [months, setMonths] = useState(6)
  const [year, setYear] = useState(new Date().getFullYear())
  const [selectedMonths, setSelectedMonths] = useState([])
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [banner, setBanner] = useState({ error: '', success: '' })

  function toggleMonth(monthNum) {
    setSelectedMonths((prev) =>
      prev.includes(monthNum) ? prev.filter((m) => m !== monthNum) : [...prev, monthNum].sort((a, b) => a - b)
    )
  }

  function handleDeleted(result) {
    setConfirmOpen(false)
    setBanner({ error: '', success: result?.message || 'Data deleted across all users.' })
  }

  const canOpenConfirm = mode === 'age' || selectedMonths.length > 0
  const monthLabel = selectedMonths.map((m) => MONTH_NAMES[m - 1]).join(', ')

  return (
    <section className="hud-card hud-danger mt-4 p-6">
      <h2 className="mb-1 text-lg font-black text-rose-300">Global Nuke</h2>
      <p className="mb-4 text-[13.6px] text-rose-200/70">
        Permanently deletes matching documents (and their exported Excel rows) across EVERY
        user simultaneously. Not scoped to any one account.
      </p>

      <Banner error={banner.error} success={banner.success} />

      <div className="mb-3 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1.5 text-[12.6px] text-rose-200/80">
          <input type="radio" checked={mode === 'age'} onChange={() => setMode('age')} />
          Age-based (oldest first)
        </label>
        <label className="flex items-center gap-1.5 text-[12.6px] text-rose-200/80">
          <input type="radio" checked={mode === 'months'} onChange={() => setMode('months')} />
          Specific year + month(s)
        </label>
      </div>

      {mode === 'age' ? (
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-[12.6px] text-rose-200/80">Delete data older than</label>
          <select
            value={months}
            onChange={(e) => setMonths(Number(e.target.value))}
            className="rounded-lg border border-rose-800/50 bg-slate-950 px-2 py-1.5 text-[12.6px] text-white"
          >
            <option value={1}>1 month</option>
            <option value={2}>2 months</option>
            <option value={3}>3 months</option>
            <option value={6}>6 months</option>
            <option value={9}>9 months</option>
          </select>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-[12.6px] text-rose-200/80">Year</label>
            <input
              type="number"
              value={year}
              onChange={(e) => setYear(e.target.value)}
              className="w-24 rounded-lg border border-rose-800/50 bg-slate-950 px-2 py-1.5 text-[12.6px] text-white"
            />
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {MONTH_NAMES.map((name, idx) => {
              const monthNum = idx + 1
              const active = selectedMonths.includes(monthNum)
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => toggleMonth(monthNum)}
                  className={`rounded-lg border px-2.5 py-1.5 text-[11.6px] font-bold transition-colors ${active ? 'border-rose-500 bg-rose-700 text-white' : 'border-rose-800/50 bg-slate-950 text-rose-200/70 hover:bg-rose-900/30'}`}
                >
                  {name.slice(0, 3)}
                </button>
              )
            })}
          </div>
        </>
      )}

      <button
        type="button"
        onClick={() => setConfirmOpen(true)}
        disabled={!canOpenConfirm}
        className="mt-4 flex items-center gap-2 rounded-xl border-2 border-rose-500 bg-gradient-to-r from-rose-700 to-red-700 px-4 py-2 text-[12.6px] font-black text-white shadow-[0_0_0_3px_rgba(244,63,94,0.15)] transition-all hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <WarningIcon />
        Global Nuke
      </button>

      <AnimatePresence>
        {confirmOpen && mode === 'age' && (
          <ConfirmPurgeModal
            title="Confirm global age-based nuke"
            message={`This will permanently delete documents and exported Excel rows older than ${months} month(s), across EVERY user's account.`}
            phrase="NUKE ALL RANGE"
            purgeFn={(body) => purgeGlobalRange({ ...body, olderThanMonths: months })}
            onClose={() => setConfirmOpen(false)}
            onDeleted={handleDeleted}
          />
        )}
        {confirmOpen && mode === 'months' && (
          <ConfirmPurgeModal
            title="Confirm global year+month nuke"
            message={`This will permanently delete documents and exported Excel rows from ${monthLabel} ${year} only, across EVERY user's account. All other months and years are left completely untouched.`}
            phrase="NUKE ALL MONTHS"
            purgeFn={(body) => purgeGlobalMonths({ ...body, year: Number(year), months: selectedMonths })}
            onClose={() => setConfirmOpen(false)}
            onDeleted={handleDeleted}
          />
        )}
      </AnimatePresence>
    </section>
  )
}

export default function AdminMaintenancePage() {
  return (
    <div className="mx-auto max-w-[900px] px-4 py-8 sm:px-6 lg:px-10">
      <BackButton fallback="/" />
      <h1 className="text-3xl font-black tracking-tight text-white">Maintenance</h1>
      <div role="alert" className="hud-card hud-danger mb-2 mt-4 flex items-start gap-3 p-4">
        <WarningIcon className="mt-0.5 h-5 w-5 shrink-0 text-rose-300" />
        <p className="text-[14px] font-semibold text-rose-100">
          These actions permanently delete data for ALL users and cannot be undone.
        </p>
      </div>
      <GlobalNukePanel />
    </div>
  )
}
