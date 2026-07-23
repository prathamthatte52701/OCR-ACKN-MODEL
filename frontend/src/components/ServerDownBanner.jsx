import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import api, { onServerDownChange } from '../api/client'

// Full-page overlay shown whenever the backend is unreachable (network error,
// connection refused, timeout) - as opposed to a normal 4xx/5xx from a server
// that IS up, which each page's own ErrorMessage already handles. Pings
// /health on mount to catch a down backend even on pages that make no API
// call themselves (e.g. sitting on the login page), then retries every 5s
// while down so it clears itself once the backend comes back.
export default function ServerDownBanner() {
  const [down, setDown] = useState(false)

  useEffect(() => {
    const unsubscribe = onServerDownChange(setDown)
    api.get('/health').catch(() => {})
    return unsubscribe
  }, [])

  useEffect(() => {
    if (!down) return
    const interval = setInterval(() => { api.get('/health').catch(() => {}) }, 5000)
    return () => clearInterval(interval)
  }, [down])

  if (!down) return null

  return (
    <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-center gap-4 bg-gray-950/95 px-4 text-center backdrop-blur-sm">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-red-900/30">
        <AlertTriangle className="h-7 w-7 text-red-400" />
      </div>
      <div>
        <p className="text-xl font-semibold text-red-400">Server is currently unreachable</p>
        <p className="mt-1 text-sm text-gray-400">Please try again shortly.</p>
      </div>
    </div>
  )
}
