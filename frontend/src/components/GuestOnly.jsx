import { Navigate, Outlet, useSearchParams } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { safeNext } from '../utils/safeNext'

// /login, /signup, /forgot-password are for logged-out visitors. A logged-in user is sent
// on (replace, so Back does not return here) - to ?next= if present, else the Dashboard.
export default function GuestOnly() {
  const user = useAuthStore((s) => s.user)
  const loading = useAuthStore((s) => s.loading)
  const [params] = useSearchParams()

  if (loading && useAuthStore.getState().token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#020817]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-transparent border-t-blue-400" />
      </div>
    )
  }
  if (user) return <Navigate to={safeNext(params.get('next'))} replace />
  return <Outlet />
}
