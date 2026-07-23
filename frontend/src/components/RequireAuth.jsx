import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

// Gate for every protected route - nothing behind this renders until a valid
// session is confirmed. Redirects to /login with the intended destination
// preserved so the user lands back where they were after logging in.
export default function RequireAuth() {
  const user = useAuthStore((s) => s.user)
  const loading = useAuthStore((s) => s.loading)
  const location = useLocation()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#020817]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-transparent border-t-blue-400" />
      </div>
    )
  }

  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }

  return <Outlet />
}
