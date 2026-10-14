import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { useAuthStore } from '../store/authStore'
import { AUTH_PATHS } from '../utils/safeNext'
import { previousPath, recordLocation } from './routeHistory'

// Goes back inside the app only: browser history when this tab has in-app history,
// otherwise `fallback` (replace, so Back never bounces to the page it just left).
// `to` forces a target; `onBack` replaces the behaviour entirely (login status card).
export default function BackButton({ fallback = '/', to, onBack, className = '' }) {
  const navigate = useNavigate()
  const location = useLocation()
  const loggedIn = useAuthStore((s) => Boolean(s.user))
  const busy = useRef(false)

  useEffect(() => {
    recordLocation(location.pathname)
    busy.current = false
  }, [location.key, location.pathname])

  function handleClick() {
    if (onBack) return onBack()
    if (to) return navigate(to)
    // Rapid clicks would queue several navigate(-1) and walk out of the app.
    if (busy.current) return
    busy.current = true
    setTimeout(() => { busy.current = false }, 600)

    const hasHistory = location.key !== 'default' || (window.history.state?.idx ?? 0) > 0
    if (!hasHistory) return navigate(fallback, { replace: true })
    if (loggedIn && AUTH_PATHS.includes(previousPath())) return navigate('/', { replace: true })
    navigate(-1)
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-label="Go back"
      className={`mb-4 inline-flex min-h-[40px] min-w-[40px] shrink-0 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.045] px-3.5 text-[14.7px] font-bold text-slate-200 transition-colors hover:border-blue-300/30 hover:bg-blue-500/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#020817] ${className}`}
    >
      <ArrowLeft className="h-4 w-4" aria-hidden="true" />
      Back
    </button>
  )
}
