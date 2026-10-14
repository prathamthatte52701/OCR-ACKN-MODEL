import { useEffect } from 'react'
import { fetchMe } from '../api/auth'
import { useAuthStore } from '../store/authStore'

// Runs once at app startup - restores the session from the stored token by
// re-verifying it against GET /auth/me (rather than trusting a decoded JWT
// client-side), mirroring the old AuthContext's mount effect.
export function useInitAuth() {
  const token = useAuthStore((s) => s.token)
  const setUser = useAuthStore((s) => s.setUser)
  const setLoading = useAuthStore((s) => s.setLoading)
  const clear = useAuthStore((s) => s.clear)

  // Logging out in another tab removes the token from localStorage - follow it here so
  // this tab cannot keep showing (or navigating Back to) protected pages.
  useEffect(() => {
    function onStorage(e) {
      if (e.key === 'ackintel_token' && !e.newValue) clear()
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    let cancelled = false
    if (!token) {
      setLoading(false)
      return
    }
    fetchMe()
      .then((user) => { if (!cancelled) setUser(user) })
      .catch(() => { if (!cancelled) clear() })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}
