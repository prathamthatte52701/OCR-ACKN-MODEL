import { FileText } from 'lucide-react'

export default function ProcessingState({ message = 'Processing document...' }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 px-4 py-20 text-center">
      <div className="relative h-16 w-16">
        <div className="h-16 w-16 rounded-full border-2 border-gray-700" />
        <div className="absolute inset-0 h-16 w-16 animate-spin rounded-full border-2 border-t-blue-500 border-r-blue-400" />
        <div className="absolute inset-3 flex items-center justify-center text-gray-300">
          <FileText className="h-6 w-6" />
        </div>
      </div>
      <div>
        <p className="font-medium text-white">{message}</p>
        <p className="mt-1 text-sm text-gray-500">This may take a few moments.</p>
      </div>
      <div className="flex gap-1.5">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-2 w-2 animate-bounce rounded-full bg-blue-500"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    </div>
  )
}
