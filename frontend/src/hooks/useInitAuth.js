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
