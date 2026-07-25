import { useEffect, useRef, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { AlertCircle } from 'lucide-react'
import { uploadDocument, getDocument, bulkUploadDocuments } from '../api/documents'
import { validateDocumentFile } from '../utils/documentValidation'
import UploadCard from '../components/UploadCard'
import { displayNumber } from '../utils/documentDisplay'
import challanRouteVisual from '../assets/transport-bill-route-visual.png'

const DOCUMENT_TYPES = ['Tax Invoice', 'Delivery Challan']
const MAX_BULK_FILES = 5
const RESULTS_PAGE_SIZE = 5
// Bulk files process strictly sequentially on the server, but every file's
// poll timer starts at upload time regardless of queue position - a flat
// single-upload-sized budget (90 attempts/180s) meant a file queued behind
// 3-4 others could still be legitimately processing when its own clock ran
// out, showing as "failed" client-side even though the backend kept going
// and finished it correctly moments later. Matches the 500s backend OCR
// budget so a file's poll window comfortably covers realistic worst-case
// queue wait + its own processing time.
const BULK_POLL_MAX_ATTEMPTS = 250

function LogisticsUploadIllustration() {
  return (
    <div className="relative mt-10 hidden min-h-[310px] overflow-hidden rounded-[30px] border border-blue-300/10 bg-slate-950/20 lg:block">
      <img
        src={challanRouteVisual}
        alt="Acknowledgement upload visual"
        className="absolute inset-0 h-full w-full object-cover object-center"
      />
      <div className="absolute inset-0 bg-gradient-to-t from-slate-950/55 via-transparent to-slate-950/10" />
      <div className="absolute left-5 top-5 rounded-full border border-blue-300/20 bg-blue-500/12 px-4 py-2 text-[10.5px] font-bold uppercase tracking-[0.18em] text-blue-100 backdrop-blur-xl">
        Acknowledgement Intake
      </div>
    </div>
  )
}

function GuidelineCard() {
  return (
    <div className="rounded-3xl border border-blue-300/12 bg-slate-950/44 p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
      <div className="flex gap-4">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-blue-300/20 bg-blue-500/15 text-[14.7px] font-black text-blue-200 shadow-[0_0_28px_rgba(37,99,235,0.24)]">i</span>
        <div className="space-y-2 text-[14.7px] leading-6 text-slate-400">
          <p>- Accepted formats: JPG, JPEG, PNG, PDF</p>
          <p>- Maximum file size: 5 MB</p>
          <p>- Pick the document type first - it decides which field(s) get extracted</p>
          <p>- Only the Number and Date from the top header are extracted; items, GST, stamps, and signatures are ignored</p>
          <p>- Processing may take a few seconds</p>
        </div>
      </div>
    </div>
  )
}

function UploadProcessingState({ message }) {
  return (
    <div className="flex min-h-[520px] flex-col items-center justify-center gap-5 rounded-[26px] border border-blue-300/12 bg-slate-950/34 px-4 py-20 text-center">
      <div className="relative h-20 w-20">
        <div className="h-20 w-20 rounded-full border border-blue-300/15 bg-blue-500/10 shadow-[0_0_48px_rgba(37,99,235,0.2)]" />
        <div className="absolute inset-0 h-20 w-20 animate-spin rounded-full border-2 border-transparent border-r-cyan-300 border-t-blue-500" />
        <div className="absolute inset-4 flex items-center justify-center rounded-full border border-white/10 bg-slate-950">
          <span className="text-[12.6px] font-black text-blue-200">OCR</span>
        </div>
      </div>
      <div>
        <p className="text-lg font-black text-white">{message}</p>
        <p className="mt-2 text-[14.7px] text-slate-500">This may take a few moments.</p>
      </div>
      <div className="flex gap-1.5">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-2 w-2 animate-bounce rounded-full bg-blue-400"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    </div>
  )
}

// Single-upload only, by design - shows the actual selected file before
// submit (image thumbnail, or the browser's native inline PDF viewer for a
// PDF) so the user can confirm it's the right document. Bulk upload
// deliberately has no equivalent - flagged as out of scope for that flow.
function FilePreview({ file }) {
  const [previewUrl, setPreviewUrl] = useState('')

  useEffect(() => {
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  if (!previewUrl) return null

  const isPdf = file.type === 'application/pdf'

  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-slate-950/40">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5">
        <span className="min-w-0 truncate text-[13.6px] font-semibold text-slate-300">{file.name}</span>
        <span className="shrink-0 text-[12.6px] text-slate-500">{(file.size / 1024).toFixed(1)} KB</span>
      </div>
      {isPdf ? (
        <embed src={previewUrl} type="application/pdf" className="h-[420px] w-full bg-slate-900" />
      ) : (
        <img src={previewUrl} alt={`Preview of ${file.name}`} className="max-h-[420px] w-full object-contain bg-slate-900" />
      )}
    </div>
  )
}

function StatusChip({ status }) {
  const styles = {
    waiting: 'border-slate-500/30 bg-slate-500/10 text-slate-400',
    processing: 'border-blue-300/30 bg-blue-500/10 text-blue-200',
    done: 'border-emerald-300/30 bg-emerald-400/10 text-emerald-200',
    failed: 'border-rose-400/30 bg-rose-500/10 text-rose-200',
  }
  const labels = { waiting: 'Waiting', processing: 'Processing', done: 'Done', failed: 'Failed' }
  return (
    <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.6px] font-bold uppercase tracking-[0.1em] ${styles[status]}`}>
      {status === 'processing' && (
        <span className="h-2.5 w-2.5 animate-spin rounded-full border-2 border-transparent border-t-blue-300 border-r-blue-300" />
      )}
      {labels[status]}
    </span>
  )
}

export default function UploadPage() {
  const [file, setFile] = useState(null)
  const [documentType, setDocumentType] = useState(DOCUMENT_TYPES[0])
  const [status, setStatus] = useState('idle') // idle | uploading | processing | done | error
  const [error, setError] = useState('')
  const pollRef = useRef(null)
  const navigate = useNavigate()

  // Bulk upload - a separate, additive flow alongside the single-file one
  // above. Nothing in this block changes single-file state/handlers.
  const [mode, setMode] = useState('single') // 'single' | 'bulk'
  const [bulkFiles, setBulkFiles] = useState([]) // [{ file, documentType, status, error, docId }]
  const [bulkError, setBulkError] = useState('')
  const [bulkSubmitting, setBulkSubmitting] = useState(false)
  const [resultsPage, setResultsPage] = useState(1)
  const bulkPollRef = useRef(null)
  // setInterval's closure would otherwise see bulkFiles as it was when the
  // interval was created - this ref is kept in sync so each tick reads the
  // current list instead of a stale one.
  const bulkFilesRef = useRef([])
  useEffect(() => { bulkFilesRef.current = bulkFiles }, [bulkFiles])

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      if (bulkPollRef.current) clearInterval(bulkPollRef.current)
    }
  }, [])

  async function handleUpload() {
    if (!file) return
    setStatus('uploading')
    setError('')

    try {
      const doc = await uploadDocument(file, documentType)
      const docId = doc?._id
      if (!docId) throw new Error('Upload failed: no document ID returned.')

      setStatus('processing')

      if (pollRef.current) clearInterval(pollRef.current)
      let attempts = 0
      pollRef.current = setInterval(async () => {
        attempts++
        let shouldTimeout = false
        try {
          const polled = await getDocument(docId)

          if (polled?.uploadStatus === 'processed') {
            clearInterval(pollRef.current)
            pollRef.current = null
            setStatus('done')
            setTimeout(() => navigate(`/documents/${docId}`), 800)
          } else if (polled?.uploadStatus === 'failed') {
            clearInterval(pollRef.current)
            pollRef.current = null
            setStatus('error')
            setError(polled.processingError || 'We could not process this document. Please try uploading it again.')
          } else if (attempts > 90) {
            shouldTimeout = true
          }
        } catch {
          shouldTimeout = attempts > 90
        }

        if (shouldTimeout) {
          clearInterval(pollRef.current)
          pollRef.current = null
          setStatus('error')
          // Processing may still finish on the server even after we stop
          // waiting here - say that explicitly instead of implying it failed.
          setError('This is taking longer than expected. It may still finish processing in the background - check My Documents in a minute before uploading again.')
        }
      }, 2000)
    } catch (err) {
      setStatus('error')
      setError(err.userMessage || 'Could not upload this document. Please try again.')
    }
  }

  function handleReset() {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    setFile(null)
    setStatus('idle')
    setError('')
  }

  const isProcessing = status === 'uploading' || status === 'processing'

  // -- Bulk upload -----------------------------------------------------------

  function handleBulkFileSelect(e) {
    const selected = Array.from(e.target.files || [])
    e.target.value = ''
    if (selected.length === 0) return

    if (bulkFiles.length + selected.length > MAX_BULK_FILES) {
      setBulkError(`You can upload a maximum of ${MAX_BULK_FILES} files at once.`)
      return
    }

    const additions = []
    for (const f of selected) {
      const err = validateDocumentFile(f)
      if (err) {
        setBulkError(`${f.name}: ${err}`)
        return
      }
      additions.push({ file: f, documentType: DOCUMENT_TYPES[0], status: 'waiting', error: '', docId: null })
    }
    setBulkError('')
    setBulkFiles((prev) => [...prev, ...additions])
  }

  function removeBulkFile(index) {
    setBulkFiles((prev) => prev.filter((_, i) => i !== index))
  }

  function setBulkFileType(index, type) {
    setBulkFiles((prev) => prev.map((f, i) => (i === index ? { ...f, documentType: type } : f)))
  }

  function startBulkPolling() {
    if (bulkPollRef.current) clearInterval(bulkPollRef.current)
    let attempts = 0

    bulkPollRef.current = setInterval(async () => {
      attempts++
      const current = bulkFilesRef.current
      const pending = current.filter((f) => f.status === 'processing' && f.docId)

      if (pending.length === 0) {
        clearInterval(bulkPollRef.current)
        bulkPollRef.current = null
        setBulkSubmitting(false)
        return
      }

      // Polling is just a status read per file, not processing - running
      // these checks together doesn't run OCR concurrently, the server's
      // own single-slot queue already guarantees only one file is actually
      // being worked on at any moment.
      const updates = await Promise.all(pending.map(async (f) => {
        try {
          const polled = await getDocument(f.docId)
          if (polled?.uploadStatus === 'processed') {
            return {
              docId: f.docId,
              status: 'done',
              taxInvoiceNo: polled.taxInvoiceNo,
              referenceNo: polled.referenceNo,
              number: polled.number,
              date: polled.date,
            }
          }
          if (polled?.uploadStatus === 'failed') return { docId: f.docId, status: 'failed', error: polled.processingError || 'Processing failed.' }
          if (attempts > BULK_POLL_MAX_ATTEMPTS) return { docId: f.docId, status: 'failed', error: 'This is taking longer than expected. Check My Documents shortly.' }
          return null
        } catch {
          if (attempts > BULK_POLL_MAX_ATTEMPTS) return { docId: f.docId, status: 'failed', error: 'Could not check status. Check My Documents shortly.' }
          return null
        }
      }))

      const changed = updates.filter(Boolean)
      if (changed.length > 0) {
        setBulkFiles((prev) => prev.map((f) => {
          const u = changed.find((c) => c.docId === f.docId)
          if (!u) return f
          return {
            ...f,
            status: u.status,
            error: u.error || '',
            taxInvoiceNo: u.taxInvoiceNo,
            referenceNo: u.referenceNo,
            number: u.number,
            date: u.date,
          }
        }))
      }
    }, 2000)
  }

  async function handleBulkUpload() {
    if (bulkFiles.length === 0) return
    setBulkSubmitting(true)
    setBulkError('')
    setBulkFiles((prev) => prev.map((f) => ({ ...f, status: 'processing' })))

    try {
      const results = await bulkUploadDocuments(
        bulkFiles.map((f) => f.file),
        bulkFiles.map((f) => f.documentType)
      )

      setBulkFiles((prev) => prev.map((f, i) => {
        const r = results[i]
        if (!r) return { ...f, status: 'failed', error: 'No result returned for this file.' }
        if (r.error) return { ...f, status: 'failed', error: r.error }
        return { ...f, status: 'processing', docId: r.document._id }
      }))
      startBulkPolling()
    } catch (err) {
      setBulkSubmitting(false)
      const message = err.userMessage || 'Upload failed. Please try again.'
      setBulkFiles((prev) => prev.map((f) => ({ ...f, status: 'failed', error: message })))
    }
  }

  function handleBulkReset() {
    if (bulkPollRef.current) {
      clearInterval(bulkPollRef.current)
      bulkPollRef.current = null
    }
    setBulkFiles([])
    setBulkError('')
    setBulkSubmitting(false)
    setResultsPage(1)
  }

  const bulkDoneCount = bulkFiles.filter((f) => f.status === 'done').length
  const bulkFailedCount = bulkFiles.filter((f) => f.status === 'failed').length
  const bulkTotal = bulkFiles.length
  const bulkAllSettled = bulkTotal > 0 && bulkDoneCount + bulkFailedCount === bulkTotal

  const resultsTotalPages = Math.max(1, Math.ceil(bulkFiles.length / RESULTS_PAGE_SIZE))
  const resultsPageItems = bulkFiles.slice(
    (resultsPage - 1) * RESULTS_PAGE_SIZE,
    resultsPage * RESULTS_PAGE_SIZE
  )

  return (
    <div className="relative min-h-full overflow-hidden bg-[#020817]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_8%_14%,rgba(37,99,235,0.2),transparent_30%),radial-gradient(circle_at_78%_18%,rgba(6,182,212,0.16),transparent_28%),linear-gradient(180deg,rgba(15,23,42,0.16),rgba(2,6,23,0.98))]" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.035)_1px,transparent_1px)] bg-[size:56px_56px] opacity-55" />

      <main className="relative mx-auto grid max-w-[1440px] gap-8 px-4 py-8 sm:px-6 lg:min-h-[calc(100vh-94px)] lg:grid-cols-[0.75fr_1.25fr] lg:items-center lg:px-10 lg:py-12">
        <section className="max-w-xl">
          <p className="mb-6 text-[14.7px] font-bold text-blue-400">Upload Document</p>
          <h1 className="text-4xl font-black leading-[1.16] tracking-[-0.035em] text-white sm:text-5xl xl:text-[56px]">
            Extract. Verify.
            <span className="block">Number and date,</span>
            <span className="block text-blue-400 drop-shadow-[0_0_28px_rgba(59,130,246,0.55)]">in seconds.</span>
          </h1>
          <p className="mt-6 max-w-lg text-base leading-8 text-slate-400">
            Pick the document type, upload one file, and the header number and date are extracted automatically.
          </p>
          <LogisticsUploadIllustration />
        </section>

        <section className="rounded-[32px] border border-blue-300/18 bg-slate-900/62 p-5 shadow-[0_34px_120px_rgba(2,8,23,0.55),inset_0_1px_0_rgba(255,255,255,0.08)] backdrop-blur-xl sm:p-7">
          <div className="mb-5 flex gap-2">
            <button
              type="button"
              onClick={() => setMode('single')}
              disabled={isProcessing || bulkSubmitting}
              className={`flex-1 rounded-2xl border px-4 py-2.5 text-[13.6px] font-bold transition-all disabled:cursor-not-allowed disabled:opacity-50 ${
                mode === 'single'
                  ? 'border-blue-300/50 bg-blue-500/15 text-blue-100'
                  : 'border-white/10 bg-white/[0.03] text-slate-400 hover:border-blue-300/25 hover:text-slate-200'
              }`}
            >
              Single Upload
            </button>
            <button
              type="button"
              onClick={() => setMode('bulk')}
              disabled={isProcessing || bulkSubmitting}
              className={`flex-1 rounded-2xl border px-4 py-2.5 text-[13.6px] font-bold transition-all disabled:cursor-not-allowed disabled:opacity-50 ${
                mode === 'bulk'
                  ? 'border-blue-300/50 bg-blue-500/15 text-blue-100'
                  : 'border-white/10 bg-white/[0.03] text-slate-400 hover:border-blue-300/25 hover:text-slate-200'
              }`}
            >
              Bulk Upload (up to {MAX_BULK_FILES})
            </button>
          </div>

          {mode === 'bulk' ? (
            bulkAllSettled ? (
              <div className="flex min-h-[460px] flex-col gap-5 rounded-[26px] border border-blue-300/12 bg-slate-950/34 px-5 py-8">
                <div className="flex flex-col items-center gap-4 text-center">
                  <div
                    className={`grid h-20 w-20 place-items-center rounded-full border text-[13.6px] font-black shadow-[0_0_45px_rgba(16,185,129,0.18)] ${
                      bulkFailedCount === 0
                        ? 'border-emerald-300/25 bg-emerald-400/15 text-emerald-200'
                        : 'border-amber-300/25 bg-amber-400/15 text-amber-200'
                    }`}
                  >
                    {bulkDoneCount}/{bulkTotal}
                  </div>
                  <p className="text-xl font-black text-white">View All Results</p>
                  <p className="text-[14.7px] text-slate-400">
                    {bulkFailedCount === 0
                      ? `${bulkDoneCount}/${bulkTotal} processed successfully`
                      : `${bulkDoneCount}/${bulkTotal} processed, ${bulkFailedCount} failed`}
                  </p>
                </div>

                <div className="w-full space-y-2 text-left">
                  {resultsPageItems.map((f, i) => (
                    <div key={i} className="grid grid-cols-[1fr_auto_auto_auto_auto] items-center gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3">
                      <span className="min-w-0 truncate text-[13.6px] text-slate-300" title={f.file.name}>{f.file.name}</span>
                      <span className="shrink-0 text-[12.6px] text-slate-500">{f.documentType}</span>
                      <span className="shrink-0 text-[12.6px] font-semibold text-slate-300">{f.status === 'done' ? displayNumber(f) : '-'}</span>
                      <span className="shrink-0 text-[12.6px] font-semibold text-slate-300">{f.status === 'done' ? (f.date || '-') : '-'}</span>
                      {f.status === 'done' && f.docId ? (
                        <Link to={`/documents/${f.docId}`} className="shrink-0 text-[12.6px] font-bold text-emerald-300 no-underline hover:underline">
                          Review
                        </Link>
                      ) : (
                        <span className="shrink-0 text-[12.6px] font-bold text-rose-300" title={f.error}>Failed</span>
                      )}
                    </div>
                  ))}
                </div>

                {resultsTotalPages > 1 && (
                  <div className="flex items-center justify-center gap-4">
                    <button
                      onClick={() => setResultsPage((p) => Math.max(1, p - 1))}
                      disabled={resultsPage <= 1}
                      className="inline-flex items-center justify-center rounded-2xl border border-white/10 bg-white/[0.045] px-5 py-3 text-[14.7px] font-bold text-slate-200 transition-colors hover:border-blue-300/30 hover:bg-blue-500/10 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-white/10 disabled:hover:bg-white/[0.045]"
                    >
                      Previous
                    </button>
                    <span className="text-[14.7px] font-bold text-slate-400">
                      Page {resultsPage} of {resultsTotalPages}
                    </span>
                    <button
                      onClick={() => setResultsPage((p) => Math.min(resultsTotalPages, p + 1))}
                      disabled={resultsPage >= resultsTotalPages}
                      className="inline-flex items-center justify-center rounded-2xl border border-white/10 bg-white/[0.045] px-5 py-3 text-[14.7px] font-bold text-slate-200 transition-colors hover:border-blue-300/30 hover:bg-blue-500/10 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-white/10 disabled:hover:bg-white/[0.045]"
                    >
                      Next
                    </button>
                  </div>
                )}

                <button
                  onClick={handleBulkReset}
                  className="mx-auto rounded-2xl border border-white/10 bg-white/[0.045] px-6 py-3 text-[14.7px] font-bold text-slate-200 transition-all hover:border-blue-300/30 hover:bg-blue-500/10"
                >
                  Start New Batch
                </button>
              </div>
            ) : bulkSubmitting ? (
              <div className="space-y-3">
                <p className="flex items-center justify-center gap-2.5 text-center text-[14.7px] font-bold text-slate-300">
                  <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-transparent border-r-cyan-300 border-t-blue-500" />
                  Processing {bulkDoneCount + bulkFailedCount}/{bulkTotal}...
                </p>
                {bulkFiles.map((f, i) => (
                  <div key={i} className="flex items-center justify-between gap-3 rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3">
                    <span className="min-w-0 truncate text-[13.6px] text-slate-300">
                      {f.file.name} <span className="text-slate-600">- {f.documentType}</span>
                    </span>
                    <StatusChip status={f.status} />
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-5">
                {bulkError && (
                  <div className="flex items-start gap-3 rounded-2xl border border-rose-400/25 bg-rose-500/10 px-4 py-3 text-[14.7px] text-rose-200">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{bulkError}</span>
                  </div>
                )}

                <label className="block cursor-pointer rounded-[26px] border border-dashed border-slate-500/60 bg-slate-950/30 p-8 text-center transition-all hover:border-blue-300/75 hover:bg-blue-500/[0.045]">
                  <input type="file" accept=".jpg,.jpeg,.png,.pdf" multiple className="hidden" onChange={handleBulkFileSelect} />
                  <p className="text-[14.7px] font-bold text-white">Click to select up to {MAX_BULK_FILES} files</p>
                  <p className="mt-1 text-[12.6px] text-slate-500">JPG, JPEG, PNG, PDF - max 5MB each</p>
                </label>

                {bulkFiles.length > 0 && (
                  <div className="space-y-2">
                    {bulkFiles.map((f, i) => (
                      <div key={i} className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3">
                        <span className="min-w-0 flex-1 truncate text-[13.6px] text-slate-300">{f.file.name}</span>
                        <select
                          value={f.documentType}
                          onChange={(e) => setBulkFileType(i, e.target.value)}
                          className="rounded-lg border border-white/10 bg-slate-900 px-2 py-1.5 text-[12.6px] font-semibold text-slate-200 focus:outline-none focus:border-blue-300/40"
                        >
                          {DOCUMENT_TYPES.map((t) => (
                            <option key={t} value={t}>{t}</option>
                          ))}
                        </select>
                        <button
                          onClick={() => removeBulkFile(i)}
                          className="shrink-0 text-[12.6px] font-bold text-rose-300 hover:text-rose-200"
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {bulkFiles.length > 0 && (
                  <button
                    onClick={handleBulkUpload}
                    className="w-full rounded-2xl bg-gradient-to-r from-blue-600 to-cyan-500 px-5 py-3.5 text-[14.7px] font-black text-white shadow-[0_18px_45px_rgba(37,99,235,0.3)] transition-all hover:-translate-y-0.5 hover:shadow-[0_22px_60px_rgba(37,99,235,0.42)]"
                  >
                    Upload All ({bulkFiles.length})
                  </button>
                )}

                <GuidelineCard />
              </div>
            )
          ) : isProcessing ? (
            <UploadProcessingState
              message={status === 'uploading' ? 'Uploading document...' : 'Running OCR + AI analysis...'}
            />
          ) : status === 'done' ? (
            <div className="flex min-h-[460px] flex-col items-center justify-center gap-4 rounded-[26px] border border-emerald-300/18 bg-emerald-400/8 px-5 py-16 text-center">
              <div className="grid h-20 w-20 place-items-center rounded-full border border-emerald-300/25 bg-emerald-400/15 text-[14.7px] font-black text-emerald-200 shadow-[0_0_45px_rgba(16,185,129,0.22)]">Done</div>
              <div>
                <p className="text-xl font-black text-white">Document processed</p>
                <p className="mt-2 text-[14.7px] text-slate-500">Redirecting...</p>
              </div>
            </div>
          ) : (
            <div className="space-y-5">
              <div>
                <p className="mb-2 text-sm font-bold text-blue-300">Document Type</p>
                <div className="grid grid-cols-2 gap-3">
                  {DOCUMENT_TYPES.map((type) => (
                    <button
                      key={type}
                      type="button"
                      onClick={() => setDocumentType(type)}
                      disabled={isProcessing}
                      className={`rounded-2xl border px-4 py-3 text-[14.7px] font-bold transition-all ${
                        documentType === type
                          ? 'border-blue-300/60 bg-blue-500/15 text-blue-100 shadow-[0_0_28px_rgba(37,99,235,0.24)]'
                          : 'border-white/10 bg-white/[0.03] text-slate-400 hover:border-blue-300/30 hover:text-slate-200'
                      }`}
                    >
                      {type}
                    </button>
                  ))}
                </div>
              </div>

              <UploadCard onFileSelect={setFile} disabled={isProcessing} />

              {file && !isProcessing && <FilePreview file={file} />}

              {error && (
                <div className="flex items-start gap-3 rounded-2xl border border-rose-400/25 bg-rose-500/10 px-4 py-3 text-[14.7px] text-rose-200">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {file && (
                <div className="flex flex-col gap-3 sm:flex-row">
                  <button
                    onClick={handleUpload}
                    disabled={isProcessing}
                    className="flex-1 rounded-2xl bg-gradient-to-r from-blue-600 to-cyan-500 px-5 py-3.5 text-[14.7px] font-black text-white shadow-[0_18px_45px_rgba(37,99,235,0.3)] transition-all hover:-translate-y-0.5 hover:shadow-[0_22px_60px_rgba(37,99,235,0.42)] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Upload & Process
                  </button>
                  <button
                    onClick={handleReset}
                    className="rounded-2xl border border-white/10 bg-white/[0.045] px-6 py-3.5 text-[14.7px] font-bold text-slate-300 transition-all hover:border-blue-300/25 hover:bg-blue-500/10 hover:text-white"
                  >
                    Clear
                  </button>
                </div>
              )}

              <GuidelineCard />
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
