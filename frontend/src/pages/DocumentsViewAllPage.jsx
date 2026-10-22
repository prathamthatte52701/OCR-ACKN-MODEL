import { useState } from 'react'
import { keepPreviousData } from '@tanstack/react-query'
import { useDocumentsList } from '../hooks/useDocumentsQueries'
import PageBackground from '../components/PageBackground'
import BackButton from '../components/BackButton'

const PAGE_SIZE = 30
const EMPTY_DOCUMENTS = []

// Mirrors backend/app/features/excel/service.py::_format_number_cell exactly -
// this column must show what would actually land in the Excel export for
// this row, not just "whatever field looks like a number".
function formatNumberCell(doc) {
  if (doc.documentType === 'Tax Invoice') {
    return [doc.taxInvoiceNo, doc.referenceNo].filter(Boolean).join(' / ') || '-'
  }
  return doc.number || '-'
}

const COLUMNS = [
  { key: 'documentType', label: 'Document Type' },
  { key: 'number', label: 'Number' },
  { key: 'date', label: 'Date' },
  { key: 'uploadStatus', label: 'Upload Status' },
  { key: 'edited', label: 'Edited' },
  { key: 'createdAt', label: 'Created At' },
]

export default function DocumentsViewAllPage() {
  const [sortKey, setSortKey] = useState(null)
  const [sortDir, setSortDir] = useState('asc')
  const [page, setPage] = useState(1)

  // No sort/order params until a header is clicked, so the server default (createdAt desc) applies.
  const params = sortKey
    ? { page, limit: PAGE_SIZE, sort: sortKey, order: sortDir }
    : { page, limit: PAGE_SIZE }
  const { data, isLoading, isError, error, refetch } = useDocumentsList(params, {
    placeholderData: keepPreviousData,
  })
  const documents = data?.documents || EMPTY_DOCUMENTS
  const totalDocuments = data?.totalDocuments ?? 0
  const totalPages = Math.max(1, data?.totalPages ?? 1)

  // Deleted-elsewhere clamp (setState during render, React-sanctioned; only ever lowers page, so no loop).
  if (data && page > totalPages) setPage(totalPages)

  function toggleSort(key) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
    setPage(1)
  }

  return (
    <div className="relative min-h-full overflow-hidden bg-[#020817]">
      <PageBackground variant="dots" />

      <main className="relative mx-auto max-w-[1440px] px-4 py-8 sm:px-6 lg:px-10 lg:py-10">

        <BackButton fallback="/documents" />
        <div className="mb-7 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-3xl font-black tracking-[-0.03em] text-white sm:text-4xl">View All Details</h1>
            <p className="mt-2 flex items-center gap-2 text-[14.7px] font-medium text-slate-500">
              <span className="h-2 w-2 rounded-full bg-blue-400 shadow-[0_0_16px_rgba(96,165,250,0.85)]" />
              {isLoading ? 'Loading documents...' : `${totalDocuments} document${totalDocuments !== 1 ? 's' : ''}`}
            </p>
          </div>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-16">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-transparent border-t-blue-400" />
          </div>
        ) : isError ? (
          <div className="rounded-[28px] border border-rose-400/25 bg-rose-500/10 p-8 text-center shadow-[0_24px_80px_rgba(127,29,29,0.16)]">
            <p className="text-lg font-black text-white">{error?.userMessage || 'Could not load your documents. Please try again.'}</p>
            <button
              onClick={refetch}
              className="mt-5 rounded-2xl border border-white/10 bg-white/[0.045] px-5 py-3 text-[14.7px] font-bold text-slate-200 transition-colors hover:border-rose-300/30 hover:bg-rose-500/10"
            >
              Try Again
            </button>
          </div>
        ) : totalDocuments === 0 ? (
          <div className="rounded-[30px] border border-blue-300/12 bg-slate-900/62 p-10 text-center shadow-[0_28px_100px_rgba(2,8,23,0.35)] backdrop-blur-xl">
            <h2 className="text-2xl font-black text-white">No documents yet</h2>
            <p className="mx-auto mt-2 max-w-md text-[14.7px] leading-6 text-slate-500">
              Upload a document to see it show up here.
            </p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto rounded-[24px] border border-blue-300/12 bg-slate-900/60">
              <table className="w-full text-left text-[13.6px]">
                <thead>
                  <tr className="border-b border-white/8 text-[11.6px] font-black uppercase tracking-wide text-slate-500">
                    {COLUMNS.map((col) => (
                      <th key={col.key} className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => toggleSort(col.key)}
                          className="inline-flex items-center gap-1 uppercase tracking-wide text-slate-500 hover:text-blue-300"
                        >
                          {col.label}
                          {sortKey === col.key && <span>{sortDir === 'asc' ? '↑' : '↓'}</span>}
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {documents.map((doc) => (
                    <tr key={doc._id} className="border-b border-white/5 last:border-0">
                      <td className="px-4 py-3 text-slate-300">{doc.documentType}</td>
                      <td className="px-4 py-3 text-slate-300">{formatNumberCell(doc)}</td>
                      <td className="px-4 py-3 text-slate-400">{doc.date || '-'}</td>
                      <td className="px-4 py-3 text-slate-400">{doc.uploadStatus}</td>
                      <td className="px-4 py-3 text-slate-400">{doc.edited ? 'Yes' : 'No'}</td>
                      <td className="px-4 py-3 text-slate-500">{doc.createdAt ? new Date(doc.createdAt).toLocaleString() : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
