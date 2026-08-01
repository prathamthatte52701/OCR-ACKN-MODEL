import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import { queryClient } from './lib/queryClient'
import { useInitAuth } from './hooks/useInitAuth'
import RequireAuth from './components/RequireAuth'
import AppLayout from './components/AppLayout'
import ServerDownBanner from './components/ServerDownBanner'
import GlobalConfirmDialog from './components/GlobalConfirmDialog'
import GlobalPromptDialog from './components/GlobalPromptDialog'
import LoginPage from './pages/LoginPage'
import SignupPage from './pages/SignupPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import Dashboard from './pages/Dashboard'
import UploadPage from './pages/UploadPage'
import DocumentsPage from './pages/DocumentsPage'
import DocumentsViewAllPage from './pages/DocumentsViewAllPage'
import DocumentDetailPage from './pages/DocumentDetailPage'
import ExportHistoryPage from './pages/ExportHistoryPage'
import MyActivityPage from './pages/MyActivityPage'
import ProfilePage from './pages/ProfilePage'
import HelpPage from './pages/HelpPage'
import NotFoundPage from './pages/NotFoundPage'

function AuthGate({ children }) {
  useInitAuth()
  return children
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ServerDownBanner />
        <GlobalConfirmDialog />
        <GlobalPromptDialog />
        <Toaster theme="dark" position="top-right" richColors closeButton />
        <AuthGate>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />

            <Route element={<RequireAuth />}>
              <Route element={<AppLayout />}>
                <Route path="/" element={<Dashboard />} />
                <Route path="/upload" element={<UploadPage />} />
                <Route path="/documents" element={<DocumentsPage />} />
                <Route path="/documents/view-all" element={<DocumentsViewAllPage />} />
                <Route path="/documents/:id" element={<DocumentDetailPage />} />
                <Route path="/export-history" element={<ExportHistoryPage />} />
                <Route path="/my-activity" element={<MyActivityPage />} />
                <Route path="/profile" element={<ProfilePage />} />
                <Route path="/help" element={<HelpPage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Route>
            </Route>

            {/* Top-level fallback - the old app only had a 404 route nested
                inside the protected tree, so an unauthenticated user hitting
                an unknown path saw nothing at all. Ported fix. */}
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </AuthGate>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
