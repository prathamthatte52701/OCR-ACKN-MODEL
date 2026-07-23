import { Link } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

export default function NotFoundPage() {
  const user = useAuthStore((s) => s.user)
  return (
    <div className="flex flex-col items-center justify-center px-4 py-24 text-center">
      <p className="mb-4 text-7xl font-bold text-gray-700">404</p>
      <h1 className="mb-2 text-2xl font-semibold text-white">Page not found</h1>
      <p className="mb-8 text-sm text-gray-500">The page you're looking for doesn't exist.</p>
      <Link
        to={user ? '/' : '/login'}
        className="rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-medium text-white no-underline transition-colors hover:bg-blue-700"
      >
        {user ? 'Go to Dashboard' : 'Go to Log in'}
      </Link>
    </div>
  )
}
