import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { Upload } from 'lucide-react'
import { useDocumentsList } from '../hooks/useDocumentsQueries'
import {
  useBulkSaveDocumentsMutation,
  useDownloadAllDocumentsMutation,
  useNewExcelFileMutation,
} from '../hooks/useDocumentMutations'
import DocumentList from '../components/DocumentList'
import PageBackground from '../components/PageBackground'
import { confirmAction, promptText } from '../store/dialogStore'
import { displayNumber } from '../utils/documentDisplay'

function DocumentsSkeleton() {
  return (
    <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="h-[250px] animate-pulse rounded-3xl border border-blue-300/10 bg-slate-900/60 p-5">
          <div className="flex gap-4">
            <div className="h-20 w-20 rounded-2xl bg-blue-500/10" />
            <div className="flex-1 space-y-3">
              <div className="h-4 w-2/3 rounded-full bg-slate-700/70" />
              <div className="h-3 w-4/5 rounded-full bg-slate-800" />
              <div className="h-3 w-1/2 rounded-full bg-slate-800" />
            </div>
          </div>
          <div className="mt-6 grid grid-cols-2 gap-3">
            <div className="h-9 rounded-xl bg-slate-800/70" />
            <div className="h-9 rounded-xl bg-slate-800/70" />
          </div>
          <div className="mt-4 h-10 rounded-xl bg-slate-800/70" />
        </div>
      ))}
    </div>
  )
}

function DocumentsError({ message, onRetry }) {
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

const PAGE_SIZE = 30
const DOCUMENT_TYPES = ['Tax Invoice', 'Delivery Challan']
const DATE_RANGES = [
  { value: 'today', label: 'Today' },
  { value: 'week', label: 'This Week' },
  { value: 'month', label: 'This Month' },
  { value: 'year', label: 'This Year' },
]

export default function DocumentsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const numberQuery = searchParams.get('number') || ''
  const dateQuery = searchParams.get('date') || ''
  const isSearching = Boolean(numberQuery || dateQuery)
  const selectedType = DOCUMENT_TYPES.includes(searchParams.get('type')) ? searchParams.get('type') : DOCUMENT_TYPES[0]
  const rangeParam = searchParams.get('range') || ''
  const selectedRange = DATE_RANGES.some((r) => r.value === rangeParam) ? rangeParam : ''

  const [page, setPage] = useState(1)
  const newExcelFileMutation = useNewExcelFileMutation()
  const bulkSaveMutation = useBulkSaveDocumentsMutation()
  const downloadAllMutation = useDownloadAllDocumentsMutation()

  // A new/changed search, group tab, or date range should always land on page 1.
  const prevSearchKeyRef = useRef(`${numberQuery}|${dateQuery}|${selectedType}|${selectedRange}`)
  useEffect(() => {
    const searchKey = `${numberQuery}|${dateQuery}|${selectedType}|${selectedRange}`
    if (searchKey !== prevSearchKeyRef.current) {
      prevSearchKeyRef.current = searchKey
      setPage(1)
    }
  }, [numberQuery, dateQuery, selectedType, selectedRange])

  const { data, isLoading, isError, error, refetch } = useDocumentsList({
    page,
    limit: PAGE_SIZE,
    documentType: selectedType,
    ...(numberQuery && { number: numberQuery }),
    ...(dateQuery && { date: dateQuery }),
    ...(selectedRange && { range: selectedRange }),
  })

  const documents = data?.documents || []
  const totalPages = data?.totalPages || 1
  const totalDocuments = data?.totalDocuments || 0

  function clearSearch() {
    const next = new URLSearchParams()
    if (searchParams.get('type')) next.set('type', searchParams.get('type'))
    if (searchParams.get('range')) next.set('range', searchParams.get('range'))
    setSearchParams(next)
  }

  function selectType(type) {
    const next = new URLSearchParams(searchParams)
    next.set('type', type)
    setSearchParams(next)
  }

  function selectRange(range) {
    const next = new URLSearchParams(searchParams)
    if (range) next.set('range', range)
    else next.delete('range')
    setSearchParams(next)
  }

  // Scoped strictly to `documents` - the already-paginated (30/page) result
  // for the CURRENT page/type/search, never the user's whole dataset. Skips
  // the per-document "already saved, are you sure?" popup on purpose (every
  // doc gets re-saved regardless of `exported`, same as an individual Save
  // Again) but still gates behind one page-level confirmation so a whole
  // page of duplicate rows is never a surprise.
  async function handleSaveAll() {
    if (documents.length === 0) return
    const ok = await confirmAction({
      title: 'Save all documents on this page?',
      message: `This will save all ${documents.length} document${documents.length !== 1 ? 's' : ''} on this page to Excel, including any already saved before. Continue?`,
      confirmLabel: 'Yes, Save All',
    })
    if (!ok) return

    try {
      const result = await bulkSaveMutation.mutateAsync(documents.map((d) => d._id))
      const failed = result.failed || []
      if (failed.length === 0) {
        toast.success(result.message)
      } else {
        const byId = new Map(documents.map((d) => [d._id, d]))
        const failedNames = failed
          .map((f) => (byId.has(f.documentId) ? displayNumber(byId.get(f.documentId)) : f.documentId))
          .join(', ')
        toast.error(`${result.message} Failed: ${failedNames}.`)
      }
    } catch (err) {
      toast.error(err.userMessage || 'Could not save documents. Please try again.')
    }
  }

  // Scoped strictly to `documents` - same page-scoping contract as Save
  // All. Documents whose original file was already hard-deleted (purge
  // file) are silently skipped server-side and reported back via response
  // headers, not an error - no confirmation needed here since downloading
  // is non-destructive, only Save All (which writes duplicate rows) gates
  // behind a popup.
  async function handleDownloadAll() {
    if (documents.length === 0) return
    try {
      const res = await downloadAllMutation.mutateAsync(documents.map((d) => d._id))
      const included = Number(res.headers?.['x-download-included'] ?? 0)
      const skipped = Number(res.headers?.['x-download-skipped'] ?? 0)
      const total = Number(res.headers?.['x-download-total'] ?? documents.length)
      if (skipped === 0) {
        toast.success(`${included} of ${total} file${total !== 1 ? 's' : ''} downloaded.`)
      } else if (included === 0) {
        toast.error(`0 of ${total} downloaded - all files were previously removed (File Delete).`)
      } else {
        toast.warning(
          `${included} of ${total} files downloaded. ${skipped} document${skipped !== 1 ? 's were' : ' was'} skipped because ${skipped !== 1 ? 'their' : 'its'} original file was previously removed (File Delete).`
        )
      }
    } catch (err) {
      toast.error(err.userMessage || 'Could not download documents. Please try again.')
    }
  }

  async function handleStartNewExcelFile() {
    const filename = await promptText({
      title: 'Start a new Excel file',
      message: 'Name for the new Excel export file:',
      placeholder: 'e.g. Bills_2026',
    })
    if (!filename) return
    try {
      const result = await newExcelFileMutation.mutateAsync(filename)
      toast.success(`New workbook "${result.filename}.xlsx" is ready. Future saves will go into this file.`)
    } catch (err) {
      toast.error(err.userMessage || 'Could not start a new Excel file. Please try again.')
    }
  }

  return (
    <div className="relative min-h-full overflow-hidden bg-[#020817]">
      <PageBackground variant="dots" />

      <main className="relative mx-auto max-w-[1440px] px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
        <div className="mb-7 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-3xl font-black tracking-[-0.03em] text-white sm:text-4xl">My Documents</h1>
            <p className="mt-2 flex items-center gap-2 text-[14.7px] font-medium text-slate-500">
              <span className="h-2 w-2 rounded-full bg-blue-400 shadow-[0_0_16px_rgba(96,165,250,0.85)]" />
              {isLoading ? 'Loading documents...' : `${totalDocuments} document${totalDocuments !== 1 ? 's' : ''}`}
            </p>
            {isSearching && (
              <div className="mt-3 flex flex-wrap items-center gap-2 text-[13.6px] text-slate-400">
                <span>
                  Filtered by{numberQuery && ` number "${numberQuery}"`}{numberQuery && dateQuery && ' and'}{dateQuery && ` date ${dateQuery}`}
                </span>
                <button
                  onClick={clearSearch}
                  className="rounded-full border border-white/10 bg-white/[0.045] px-3 py-1 text-[12.6px] font-bold text-blue-300 transition-colors hover:border-blue-300/30 hover:bg-blue-500/10"
                >
                  Clear Search
                </button>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Link
              to="/documents/view-all"
              className="inline-flex items-center justify-center gap-2 rounded-2xl border border-white/10 bg-white/[0.045] px-5 py-3 text-[14.7px] font-bold text-slate-200 no-underline transition-colors hover:border-blue-300/30 hover:bg-blue-500/10"
            >
              View All Details
            </Link>
            <button
              onClick={handleStartNewExcelFile}
              className="inline-flex items-center justify-center gap-2 rounded-2xl border border-blue-300/20 bg-slate-900/60 px-5 py-3 text-[14.7px] font-bold text-blue-200 transition-all hover:border-blue-300/45 hover:bg-blue-500/10"
            >
              Start New Excel File
            </button>
            <Link
              to="/upload"
              className="inline-flex items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-blue-600 to-blue-500 px-5 py-3 text-[14.7px] font-black text-white no-underline shadow-[0_18px_45px_rgba(37,99,235,0.34)] transition-all hover:-translate-y-0.5 hover:shadow-[0_22px_60px_rgba(37,99,235,0.45)] focus:outline-none focus:ring-2 focus:ring-blue-300/60"
            >
              <Upload className="h-4 w-4" strokeWidth={1.8} />
              Upload New
            </Link>
          </div>
        </div>

        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div className="flex gap-2">
            {DOCUMENT_TYPES.map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => selectType(type)}
                className={`flex-1 rounded-2xl border px-4 py-2.5 text-[13.6px] font-bold transition-all sm:flex-none ${
                  selectedType === type
                    ? 'border-blue-300/50 bg-blue-500/15 text-blue-100'
                    : 'border-white/10 bg-white/[0.03] text-slate-400 hover:border-blue-300/25 hover:text-slate-200'
                }`}
              >
                {type}
              </button>
            ))}
          </div>
          <div className="inline-flex items-center gap-2.5 rounded-2xl border border-blue-300/25 bg-blue-500/10 px-4 py-2 shadow-[0_0_28px_rgba(37,99,235,0.15)]">
            <span className="text-2xl font-black leading-none text-white">{isLoading ? '-' : totalDocuments}</span>
            <span className="text-[12.6px] font-bold uppercase tracking-wide text-blue-300">
              {selectedType}{totalDocuments !== 1 ? 's' : ''} total
            </span>
          </div>
        </div>

        <div className="mb-6 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => selectRange('')}
            className={`rounded-2xl border px-4 py-2 text-[13.6px] font-bold transition-all ${
              !selectedRange
                ? 'border-blue-300/50 bg-blue-500/15 text-blue-100'
                : 'border-white/10 bg-white/[0.03] text-slate-400 hover:border-blue-300/25 hover:text-slate-200'
            }`}
          >
            All
          </button>
          {DATE_RANGES.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => selectRange(value)}
              className={`rounded-2xl border px-4 py-2 text-[13.6px] font-bold transition-all ${
                selectedRange === value
                  ? 'border-blue-300/50 bg-blue-500/15 text-blue-100'
                  : 'border-white/10 bg-white/[0.03] text-slate-400 hover:border-blue-300/25 hover:text-slate-200'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {isLoading ? (
          <DocumentsSkeleton />
        ) : isError ? (
          <DocumentsError message={error?.userMessage || 'Could not load your documents. Please try again.'} onRetry={refetch} />
        ) : isSearching && documents.length === 0 ? (
          <div className="rounded-[30px] border border-blue-300/12 bg-slate-900/62 p-10 text-center shadow-[0_28px_100px_rgba(2,8,23,0.35)] backdrop-blur-xl">
            <div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl border border-blue-300/18 bg-blue-500/10 text-[14.7px] font-black text-blue-200 shadow-[0_0_42px_rgba(37,99,235,0.2)]">N/A</div>
            <h2 className="mt-5 text-2xl font-black text-white">No results found</h2>
            <p className="mx-auto mt-2 max-w-md text-[14.7px] leading-6 text-slate-500">
              No documents match{numberQuery && ` number "${numberQuery}"`}{numberQuery && dateQuery && ' and'}{dateQuery && ` date ${dateQuery}`}.
            </p>
            <button
              onClick={clearSearch}
              className="mt-6 inline-flex rounded-2xl border border-white/10 bg-white/[0.045] px-5 py-3 text-[14.7px] font-bold text-slate-200 transition-colors hover:border-blue-300/30 hover:bg-blue-500/10"
            >
              Clear Search
            </button>
          </div>
        ) : (
          <>
            <div className="mb-5 flex flex-wrap justify-end gap-3">
              <button
                type="button"
                onClick={handleDownloadAll}
                disabled={documents.length === 0 || downloadAllMutation.isPending}
                className="inline-flex items-center justify-center gap-2 rounded-2xl border border-blue-300/25 bg-blue-500/10 px-5 py-2.5 text-[13.6px] font-black text-blue-200 transition-all hover:border-blue-300/45 hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {downloadAllMutation.isPending ? `Zipping ${documents.length}...` : `Download All (${documents.length} on this page)`}
              </button>
              <button
                type="button"
                onClick={handleSaveAll}
                disabled={documents.length === 0 || bulkSaveMutation.isPending}
                className="inline-flex items-center justify-center gap-2 rounded-2xl border border-emerald-300/25 bg-emerald-500/10 px-5 py-2.5 text-[13.6px] font-black text-emerald-200 transition-all hover:border-emerald-300/45 hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {bulkSaveMutation.isPending ? `Saving ${documents.length}...` : `Save All (${documents.length} on this page)`}
              </button>
            </div>
            <DocumentList documents={documents} startIndex={(page - 1) * PAGE_SIZE} />
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
