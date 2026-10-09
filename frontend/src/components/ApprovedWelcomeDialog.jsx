import { useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from './ui/dialog'

// Pages where the notice must never appear: the login response sets the flag a moment
// BEFORE the post-login navigation, and the dialog lives at app level precisely so it
// survives that navigation and shows on the page the user lands on.
const HIDDEN_ON = ['/login', '/signup', '/forgot-password']

// Mounted once in App.jsx. Shown a single time, on the first login after an admin approved
// the account (the server sends justApproved: true exactly once). The button, Esc and a click
// on the overlay all dismiss it for good via clearJustApproved().
export default function ApprovedWelcomeDialog() {
  const justApproved = useAuthStore((s) => s.justApproved)
  const user = useAuthStore((s) => s.user)
  const clearJustApproved = useAuthStore((s) => s.clearJustApproved)
  const { pathname } = useLocation()

  const open = Boolean(justApproved && user && !HIDDEN_ON.includes(pathname))

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) clearJustApproved() }}>
      {open && (
        <DialogContent className="max-w-sm" showClose={false}>
          <DialogHeader>
            <DialogTitle>You&apos;re approved!</DialogTitle>
          </DialogHeader>
          <div className="px-5 py-4">
            <p className="text-sm text-gray-300">
              The admin has approved your account. You can now upload and manage documents.
            </p>
          </div>
          <DialogFooter>
            <button
              onClick={clearJustApproved}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
            >
              Get started
            </button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  )
}
