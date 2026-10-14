import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAdminAuth } from '../context/AdminAuthContext'
import { previousPath, recordLocation } from '../utils/routeHistory'

const AUTH_PATHS = ['/login', '/forgot-password']

// Goes back inside the app only: browser history when this tab has in-app history,
// otherwise `fallback` (replace, so Back never bounces to the page it just left).
export default function BackButton({ fallback = '/', to, className = '' }) {
  const navigate = useNavigate()
  const location = useLocation()
  const { user } = useAdminAuth()
  const busy = useRef(false)

  useEffect(() => {
    recordLocation(location.pathname)
    busy.current = false
  }, [location.key, location.pathname])

  function handleClick() {
    if (to) return navigate(to)
    // Rapid clicks would queue several navigate(-1) and walk out of the app.
    if (busy.current) return
    busy.current = true
    setTimeout(() => { busy.current = false }, 600)

    const hasHistory = location.key !== 'default' || (window.history.state?.idx ?? 0) > 0
    if (!hasHistory) return navigate(fallback, { replace: true })
    if (user && AUTH_PATHS.includes(previousPath())) return navigate('/', { replace: true })
    navigate(-1)
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-label="Go back"
      className={`mb-4 inline-flex min-h-[40px] min-w-[40px] shrink-0 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.045] px-3.5 text-[14.7px] font-bold text-slate-200 transition-colors hover:border-emerald-300/30 hover:bg-emerald-500/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#04070d] ${className}`}
    >
      <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
      </svg>
      Back
    </button>
  )
}
