import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity } from 'lucide-react'
import { useMyActivity } from '../hooks/useDocumentsQueries'
import LoadingState from '../components/LoadingState'
import PageBackground from '../components/PageBackground'
import { formatIST } from '../utils/formatDate'
import { displayNumber } from '../utils/documentDisplay'

const PAGE_SIZE = 40

const ACTION_LABELS = {
  document_processed: 'Document processed',
  document_uploaded: 'Document uploaded',
  document_corrected: 'Document edited',
  document_edited: 'Document edited',
  document_deleted: 'Document deleted',
  document_file_purged: 'Original file removed',
  document_reprocessed: 'Document reprocessed',
}

const ACTION_BADGE = {
  document_deleted: 'border-rose-400/25 bg-rose-500/10 text-rose-200',
  document_file_purged: 'border-amber-400/25 bg-amber-500/10 text-amber-200',
}

function ActivityError({ message, onRetry }) {
  return (
    <div className="rounded-[28px] border border-rose-400/25 bg-rose-500/10 p-8 text-center shadow-[0_24px_80px_rgba(127,29,29,0.16)]">
      <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-rose-300/25 bg-rose-400/10 text-[14.7px] font-black text-rose-200">ERR</div>
      <p className="mt-4 text-lg font-black text-white">{message}</p>
      <button
        onClick={onRetry}
        className="mt-5 rounded-2xl border border-white/10 bg-white/[0.045] px-5 py-3 text-[14.7px] font-bold text-slate-200 transition-colors hover:border-rose-300/30 hover:bg-rose-500/10"
      >
        Try Again
      </button>
    </div>
  )
}

function EmptyActivity() {
  return (
    <div className="rounded-[30px] border border-blue-300/12 bg-slate-900/62 p-10 text-center shadow-[0_28px_100px_rgba(2,8,23,0.35)] backdrop-blur-xl">
      <div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl border border-blue-300/18 bg-blue-500/10 text-blue-200 shadow-[0_0_42px_rgba(37,99,235,0.2)]">
        <Activity className="h-7 w-7" />
      </div>
      <h2 className="mt-5 text-2xl font-black text-white">No activity yet</h2>
      <p className="mx-auto mt-2 max-w-md text-[14.7px] leading-6 text-slate-500">
        Actions you take on your documents - edits, deletes, and more - will show up here.
      </p>
    </div>
  )
}

export default function MyActivityPage() {
  const [page, setPage] = useState(1)
  const { data, isLoading, isError, error, refetch } = useMyActivity({ page, limit: PAGE_SIZE })

  const activity = data?.activity || []
  const totalActivity = data?.totalActivity || 0
  const totalPages = data?.totalPages || 1

  return (
    <div className="relative min-h-full overflow-hidden bg-[#020817]">
      <PageBackground variant="dots" />

      <main className="relative mx-auto max-w-[1440px] px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
        <div className="mb-7">
          <h1 className="text-3xl font-black tracking-[-0.03em] text-white sm:text-4xl">My Activity</h1>
          <p className="mt-2 flex items-center gap-2 text-[14.7px] font-medium text-slate-500">
            <span className="h-2 w-2 rounded-full bg-blue-400 shadow-[0_0_16px_rgba(96,165,250,0.85)]" />
            {isLoading ? 'Loading your activity...' : `${totalActivity} activit${totalActivity !== 1 ? 'ies' : 'y'}`}
          </p>
        </div>

        {isLoading ? (
          <div className="rounded-[28px] border border-blue-300/12 bg-slate-900/68 shadow-2xl shadow-slate-950/30 backdrop-blur-xl">
            <LoadingState message="Loading your activity..." />
          </div>
        ) : isError ? (
          <ActivityError message={error?.userMessage || 'Could not load your activity. Please try again.'} onRetry={refetch} />
        ) : activity.length === 0 ? (
          <EmptyActivity />
        ) : (
          <>
            <div className="overflow-hidden rounded-3xl border border-blue-300/12 bg-slate-900/64 shadow-[0_24px_90px_rgba(2,8,23,0.34)] backdrop-blur-xl">
              <div className="overflow-x-auto" style={{ WebkitOverflowScrolling: 'touch' }}>
                <table className="min-w-full text-[14.7px]">
                  <thead>
                    <tr className="border-b border-blue-300/12 bg-white/[0.02]">
                      <th className="px-4 py-3 text-left font-bold text-slate-400">When</th>
                      <th className="px-4 py-3 text-left font-bold text-slate-400">Action</th>
                      <th className="px-4 py-3 text-left font-bold text-slate-400">Document</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activity.map((entry) => (
                      <tr key={entry.id} className="border-b border-white/8 last:border-b-0 hover:bg-white/[0.02]">
                        <td className="whitespace-nowrap px-4 py-3 text-slate-400">{formatIST(entry.createdAt)}</td>
                        <td className="whitespace-nowrap px-4 py-3">
                          <span className={`rounded-full border px-2.5 py-1 text-[11.6px] font-black uppercase ${ACTION_BADGE[entry.action] || 'border-blue-300/25 bg-blue-500/10 text-blue-200'}`}>
                            {ACTION_LABELS[entry.action] || entry.action}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-slate-300">
                          {entry.document ? (
                            <Link to={`/documents/${entry.document.id}`} className="font-semibold text-blue-300 hover:underline">
                              {entry.document.documentType} - {displayNumber(entry.document)}
                            </Link>
                          ) : (
                            <span className="text-slate-600">No longer available</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {totalPages > 1 && (
              <div className="mt-8 flex items-center justify-center gap-4">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="inline-flex items-center justify-center rounded-2xl border border-white/10 bg-white/[0.045] px-5 py-3 text-[14.7px] font-bold text-slate-200 transition-colors hover:border-blue-300/30 hover:bg-blue-500/10 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-white/10 disabled:hover:bg-white/[0.045]"
                >
                  Previous
                </button>
                <span className="text-[14.7px] font-bold text-slate-400">
                  Page {page} of {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="inline-flex items-center justify-center rounded-2xl border border-white/10 bg-white/[0.045] px-5 py-3 text-[14.7px] font-bold text-slate-200 transition-colors hover:border-blue-300/30 hover:bg-blue-500/10 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-white/10 disabled:hover:bg-white/[0.045]"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
