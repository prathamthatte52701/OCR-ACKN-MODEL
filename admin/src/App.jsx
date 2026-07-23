import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { AdminAuthProvider } from './context/AdminAuthContext'
import RequireAdminAuth from './components/RequireAdminAuth'
import AdminLayout from './components/AdminLayout'
import ServerDownBanner from './components/ServerDownBanner'
import AdminLoginPage from './pages/AdminLoginPage'
import AdminForgotPasswordPage from './pages/AdminForgotPasswordPage'
import AdminDashboardPage from './pages/AdminDashboardPage'
import AdminProfilePage from './pages/AdminProfilePage'
import AdminUsersPage from './pages/AdminUsersPage'
import AdminUserDetailPage from './pages/AdminUserDetailPage'
import AdminDocumentsPage from './pages/AdminDocumentsPage'
import AdminWorkbooksPage from './pages/AdminWorkbooksPage'
import AdminLogsPage from './pages/AdminLogsPage'

function FadeIn({ children }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.18, ease: 'easeOut' }}
    >
      {children}
    </motion.div>
  )
}

function AppRoutes() {
  const location = useLocation()
  return (
    <AnimatePresence mode="wait" initial={false}>
      <Routes location={location} key={location.pathname}>
        <Route path="/login" element={<FadeIn><AdminLoginPage /></FadeIn>} />
        <Route path="/forgot-password" element={<FadeIn><AdminForgotPasswordPage /></FadeIn>} />

        <Route element={<RequireAdminAuth />}>
          <Route element={<AdminLayout />}>
            <Route path="/" element={<FadeIn><AdminDashboardPage /></FadeIn>} />
            <Route path="/users" element={<FadeIn><AdminUsersPage /></FadeIn>} />
            <Route path="/users/:id" element={<FadeIn><AdminUserDetailPage /></FadeIn>} />
            <Route path="/documents" element={<FadeIn><AdminDocumentsPage /></FadeIn>} />
            <Route path="/workbooks" element={<FadeIn><AdminWorkbooksPage /></FadeIn>} />
            <Route path="/logs" element={<FadeIn><AdminLogsPage /></FadeIn>} />
            <Route path="/profile" element={<FadeIn><AdminProfilePage /></FadeIn>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Route>

        {/* Unauthenticated users hitting an unknown path land on login,
            not a blank screen. */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </AnimatePresence>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <ServerDownBanner />
      <AdminAuthProvider>
        <AppRoutes />
      </AdminAuthProvider>
    </BrowserRouter>
  )
}
