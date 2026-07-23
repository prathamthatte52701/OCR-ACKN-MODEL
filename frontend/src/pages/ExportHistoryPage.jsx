import { useState } from 'react'
import { toast } from 'sonner'
import { FileSpreadsheet } from 'lucide-react'
import { downloadWorkbook } from '../api/excel'
import { useExportHistory } from '../hooks/useDocumentsQueries'
import LoadingState from '../components/LoadingState'
import PageBackground from '../components/PageBackground'
import { formatIST } from '../utils/formatDate'
import { displayNumber } from '../utils/documentDisplay'

function HistoryError({ message, onRetry }) {
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

function EmptyHistory() {
  return (
    <div className="rounded-[30px] border border-blue-300/12 bg-slate-900/62 p-10 text-center shadow-[0_28px_100px_rgba(2,8,23,0.35)] backdrop-blur-xl">
      <div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl border border-blue-300/18 bg-blue-500/10 text-blue-200 shadow-[0_0_42px_rgba(37,99,235,0.2)]">
        <FileSpreadsheet className="h-7 w-7" />
      </div>
      <h2 className="mt-5 text-2xl font-black text-white">No exports yet</h2>
      <p className="mx-auto mt-2 max-w-md text-[14.7px] leading-6 text-slate-500">
        Save a processed document to Excel from its detail page to see it show up here.
      </p>
    </div>
  )
}

export default function ExportHistoryPage() {
  const { data: exports = [], isLoading, isError, error, refetch } = useExportHistory()
  const [downloadingId, setDownloadingId] = useState(null)

  async function handleDownload(row) {
    if (!row.workbook?.year) return
    setDownloadingId(row.id)
    try {
      await downloadWorkbook({ year: row.workbook.year })
    } catch (err) {
      toast.error(err.userMessage || 'Could not download the Excel workbook. Please try again.')
    } finally {
      setDownloadingId(null)
    }
  }

  return (
    <div className="relative min-h-full overflow-hidden bg-[#020817]">
      <PageBackground variant="dots" />

      <main className="relative mx-auto max-w-[1440px] px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
        <div className="mb-7">
          <h1 className="text-3xl font-black tracking-[-0.03em] text-white sm:text-4xl">Export History</h1>
          <p className="mt-2 flex items-center gap-2 text-[14.7px] font-medium text-slate-500">
            <span className="h-2 w-2 rounded-full bg-blue-400 shadow-[0_0_16px_rgba(96,165,250,0.85)]" />
            {isLoading ? 'Loading export history...' : `${exports.length} export${exports.length !== 1 ? 's' : ''}`}
          </p>
        </div>

        {isLoading ? (
          <div className="rounded-[28px] border border-blue-300/12 bg-slate-900/68 shadow-2xl shadow-slate-950/30 backdrop-blur-xl">
            <LoadingState message="Loading export history..." />
          </div>
        ) : isError ? (
          <HistoryError message={error?.userMessage || 'Could not load export history. Please try again.'} onRetry={refetch} />
        ) : exports.length === 0 ? (
          <EmptyHistory />
        ) : (
          <div className="overflow-hidden rounded-3xl border border-blue-300/12 bg-slate-900/64 shadow-[0_24px_90px_rgba(2,8,23,0.34)] backdrop-blur-xl">
            <div className="overflow-x-auto" style={{ WebkitOverflowScrolling: 'touch' }}>
              <table className="min-w-full text-[14.7px]">
                <thead>
                  <tr className="border-b border-blue-300/12 bg-white/[0.02]">
                    <th className="px-4 py-3 text-left font-bold text-slate-400">Document Type</th>
                    <th className="px-4 py-3 text-left font-bold text-slate-400">Number</th>
                    <th className="px-4 py-3 text-left font-bold text-slate-400">Date</th>
                    <th className="px-4 py-3 text-left font-bold text-slate-400">Exported At</th>
                    <th className="px-4 py-3 text-left font-bold text-slate-400">Workbook</th>
                    <th className="px-4 py-3 text-right font-bold text-slate-400">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {exports.map((row) => (
                    <tr key={row.id} className="border-b border-white/8 last:border-b-0 hover:bg-white/[0.02]">
                      <td className="whitespace-nowrap px-4 py-3 font-semibold text-slate-200">{row.documentType}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-300">{displayNumber(row)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-300">{row.date || '-'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-400">{formatIST(row.exportedAt)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-300">
                        {row.workbook?.filename || <span className="text-slate-600">Unknown</span>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        <button
                          onClick={() => handleDownload(row)}
                          disabled={!row.workbook?.year || downloadingId === row.id}
                          className="inline-flex items-center justify-center rounded-xl border border-blue-300/18 bg-slate-950/32 px-3 py-1.5 text-[12.6px] font-bold text-blue-200 transition-all hover:border-blue-300/35 hover:bg-blue-500/10 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          {downloadingId === row.id ? 'Downloading...' : 'Download Excel'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
