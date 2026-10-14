import { Navigate, Outlet } from 'react-router-dom'
import { useAdminAuth } from '../context/AdminAuthContext'

// /login and /forgot-password are for logged-out visitors. A logged-in admin is sent to the
// Dashboard (replace, so Back does not return here).
export default function GuestOnly() {
  const { user, loading } = useAdminAuth()
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#04070d]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-transparent border-t-emerald-400" />
      </div>
    )
  }
  if (user) return <Navigate to="/" replace />
  return <Outlet />
}
