import { useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import api from '../../utils/api'
import Banner from '../../components/Banner'
import ConfirmPurgeModal from '../../components/ConfirmPurgeModal'
import WarningIcon from './WarningIcon'

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

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
// per-user "Nuke This User" action on the user detail page. The button only
// ever OPENS ConfirmPurgeModal (typed phrase + password twice); it never deletes.
export default function GlobalNukePanel({ onDeleted }) {
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
    onDeleted?.()
  }

  const canOpenConfirm = mode === 'age' || selectedMonths.length > 0
  const monthLabel = selectedMonths.map((m) => MONTH_NAMES[m - 1]).join(', ')

  return (
    <div>
      <h3 className="mb-1 text-[16px] font-bold text-white">Global Nuke</h3>
      <p className="mb-4 text-[14px] leading-6 text-rose-100/80">
        Permanently deletes matching documents (and their exported Excel rows) across EVERY
        user simultaneously. Not scoped to any one account.
      </p>

      <Banner error={banner.error} success={banner.success} />

      <div role="radiogroup" aria-label="Delete mode" className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2">
        <label className="flex cursor-pointer items-center gap-2 text-[14px] text-rose-100">
          <input type="radio" name="nuke-mode" className="h-4 w-4 accent-[var(--red)]" checked={mode === 'age'} onChange={() => setMode('age')} />
          Age-based (oldest first)
        </label>
        <label className="flex cursor-pointer items-center gap-2 text-[14px] text-rose-100">
          <input type="radio" name="nuke-mode" className="h-4 w-4 accent-[var(--red)]" checked={mode === 'months'} onChange={() => setMode('months')} />
          Specific year + month(s)
        </label>
      </div>

      {mode === 'age' ? (
        <div className="flex flex-wrap items-center gap-3">
          <label htmlFor="nuke-age" className="text-[14px] text-rose-100">Delete data older than</label>
          <select
            id="nuke-age"
            value={months}
            onChange={(e) => setMonths(Number(e.target.value))}
            className="input !w-auto"
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
            <label htmlFor="nuke-year" className="text-[14px] text-rose-100">Year</label>
            <input
              id="nuke-year"
              type="number"
              value={year}
              onChange={(e) => setYear(e.target.value)}
              className="input !w-28"
            />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {MONTH_NAMES.map((name, idx) => {
              const monthNum = idx + 1
              const active = selectedMonths.includes(monthNum)
              return (
                <button
                  key={name}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleMonth(monthNum)}
                  className={`min-h-[36px] rounded-xl border px-3 text-[13px] font-bold transition-colors ${active ? 'border-rose-300 bg-rose-500/40 text-white' : 'border-[var(--line)] bg-[rgba(10,13,44,0.8)] text-[var(--muted)] hover:bg-rose-500/15 hover:text-white'}`}
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
        className="btn btn-danger mt-5"
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
    </div>
  )
}
