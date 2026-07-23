import { Navigate, Outlet } from 'react-router-dom'
import { useAdminAuth } from '../context/AdminAuthContext'

// Gate for every protected admin route - nothing behind this renders without
// a session the app has already confirmed is role: 'admin'. Real enforcement
// is still server-side (require_admin dependency on every /api/admin/*
// route) - this only controls what the admin app itself renders/navigates to.
export default function RequireAdminAuth() {
  const { user, loading } = useAdminAuth()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#04070d]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-transparent border-t-emerald-400" />
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}
