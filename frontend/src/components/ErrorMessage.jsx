import { AlertTriangle } from 'lucide-react'

export default function ErrorMessage({ message, onRetry }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-900/30">
        <AlertTriangle className="h-6 w-6 text-red-400" />
      </div>
      <p className="font-medium text-red-400">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="rounded bg-gray-800 px-4 py-2 text-sm text-gray-300 transition-colors hover:bg-gray-700"
        >
          Try Again
        </button>
      )}
    </div>
  )
}
