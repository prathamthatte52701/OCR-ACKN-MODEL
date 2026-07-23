import { Link, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { toast } from 'sonner'
import { downloadWorkbook } from '../api/excel'
import { useDocumentsList, useTrainingStats } from '../hooks/useDocumentsQueries'
import LoadingState from '../components/LoadingState'
import PageBackground from '../components/PageBackground'
import { formatIST, isTodayIST } from '../utils/formatDate'
import challanRouteVisual from '../assets/transport-bill-route-visual.png'

const features = [
  { icon: 'UP', title: 'Upload', desc: 'Upload acknowledgement documents in JPG, JPEG, PNG, or PDF.' },
  { icon: 'OC', title: 'Header OCR', desc: 'Crops to the top header section of the page and extracts text from just that region for maximum accuracy.' },
  { icon: 'AI', title: 'AI Analysis', desc: 'Identify the document number and date automatically - Tax Invoice or Delivery Challan.' },
  { icon: 'ED', title: 'Edit', desc: 'Review and correct extracted number/date instantly.' },
  { icon: 'XL', title: 'Excel Export', desc: 'Export verified rows into a running Excel workbook with one click.' },
]

const supportedTypes = ['Tax Invoice', 'Delivery Challan']

function formatDate(dateStr) {
  if (!dateStr) return 'Not processed'
  return formatIST(dateStr, { year: undefined })
}

function formatSize(bytes) {
  if (!bytes) return '0 KB'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function StatusBadge({ status }) {
  const styles = {
    processed: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300',
    failed: 'border-rose-400/30 bg-rose-400/10 text-rose-300',
    uploaded: 'border-amber-400/30 bg-amber-400/10 text-amber-300',
  }

  return (
    <span className={`rounded-full border px-2.5 py-1 text-[11.6px] font-bold uppercase tracking-[0.14em] ${styles[status] || styles.uploaded}`}>
      {status || 'uploaded'}
    </span>
  )
}

function MiniSparkline({ color = 'blue' }) {
  const stroke = {
    blue: '#60a5fa',
    green: '#34d399',
    red: '#fb7185',
    violet: '#a78bfa',
    amber: '#fbbf24',
    cyan: '#22d3ee',
  }[color]

  return (
    <svg className="h-9 w-20 opacity-85" viewBox="0 0 96 40" fill="none" aria-hidden="true">
      <path d="M2 31C12 30 16 18 25 21C35 25 37 12 48 15C60 19 62 7 73 10C82 12 86 5 94 7" stroke={stroke} strokeWidth="2.4" strokeLinecap="round" />
      <path d="M2 31C12 30 16 18 25 21C35 25 37 12 48 15C60 19 62 7 73 10C82 12 86 5 94 7V40H2V31Z" fill={`url(#spark-${color})`} opacity="0.22" />
      <defs>
        <linearGradient id={`spark-${color}`} x1="48" x2="48" y1="6" y2="40" gradientUnits="userSpaceOnUse">
          <stop stopColor={stroke} />
          <stop offset="1" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
    </svg>
  )
}

function StatCard({ icon, label, value, helper, color }) {
  const accents = {
    blue: 'from-blue-500/20 to-cyan-400/5 border-blue-300/15 text-blue-200 shadow-blue-950/20',
    green: 'from-emerald-500/20 to-cyan-400/5 border-emerald-300/15 text-emerald-200 shadow-emerald-950/20',
    red: 'from-rose-500/20 to-orange-400/5 border-rose-300/15 text-rose-200 shadow-rose-950/20',
    violet: 'from-violet-500/20 to-blue-400/5 border-violet-300/15 text-violet-200 shadow-violet-950/20',
    amber: 'from-amber-500/20 to-orange-400/5 border-amber-300/15 text-amber-200 shadow-amber-950/20',
    cyan: 'from-cyan-500/20 to-blue-400/5 border-cyan-300/15 text-cyan-200 shadow-cyan-950/20',
  }

  return (
    <div className={`group relative overflow-hidden rounded-2xl border bg-slate-900/68 p-4 shadow-xl backdrop-blur-xl transition-all duration-300 hover:-translate-y-1 hover:border-blue-300/25 ${accents[color]}`}>
      <div className={`absolute inset-0 bg-gradient-to-br ${accents[color]} opacity-80`} />
      <div className="relative flex items-start justify-between gap-3">
        <div>
          <span className="mb-3 grid h-10 w-10 place-items-center rounded-2xl border border-white/10 bg-white/[0.06] text-[12.6px] font-black tracking-wide">
            {icon}
          </span>
          <p className="text-2xl font-black tracking-tight text-white">{value}</p>
          <p className="mt-1 text-[14.7px] font-semibold text-slate-300">{label}</p>
          <p className="mt-1.5 text-[12.6px] text-slate-500">{helper}</p>
        </div>
        <MiniSparkline color={color} />
      </div>
    </div>
  )
}

function HeroIllustration() {
  return (
    <div className="relative min-h-[270px] overflow-hidden rounded-[28px] border border-blue-300/12 bg-slate-950/40 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
      <img
        src={challanRouteVisual}
        alt="AI acknowledgement extraction visual"
        className="absolute inset-0 h-full w-full object-cover object-center"
      />
      <div className="absolute inset-0 bg-gradient-to-r from-slate-950/15 via-transparent to-slate-950/30" />
      <div className="absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-slate-950/70 to-transparent" />
      <div className="absolute bottom-5 right-5 rounded-2xl border border-cyan-300/20 bg-slate-900/82 px-4 py-3 shadow-[0_18px_60px_rgba(8,47,73,0.38)] backdrop-blur-xl">
        <p className="text-[10.5px] font-bold uppercase tracking-[0.2em] text-cyan-200">AI Extraction</p>
        <p className="mt-1 text-2xl font-black text-white">Ready</p>
      </div>
    </div>
  )
}

function RecentDocumentRow({ doc }) {
  return (
    <Link
      to={`/documents/${doc._id}`}
      className="group grid grid-cols-[auto_1fr_auto] items-center gap-3 rounded-2xl border border-white/8 bg-white/[0.035] px-4 py-3 no-underline transition-all hover:border-blue-300/25 hover:bg-blue-500/[0.055]"
    >
      <span className="grid h-11 w-11 place-items-center rounded-2xl border border-blue-300/15 bg-blue-500/10 text-[12.6px] font-black text-blue-200">
        {doc.mimeType === 'application/pdf' ? 'PDF' : 'IMG'}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[14.7px] font-bold text-white">{doc.autoName}</span>
        <span className="mt-1 block truncate text-[12.6px] text-slate-500">{doc.documentType || doc.originalFilename}</span>
        <span className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11.6px] font-medium text-slate-600">
          <span>{formatDate(doc.createdAt)}</span>
          <span>{formatSize(doc.size)}</span>
          <span>{doc.mimeType?.split('/')[1]?.toUpperCase() || 'FILE'}</span>
        </span>
      </span>
      <StatusBadge status={doc.uploadStatus} />
    </Link>
  )
}

function QualityPanel({ stats, training }) {
  const processed = stats.processed || 0
  const failed = stats.failed || 0
  const totalChecked = processed + failed
  const quality = totalChecked ? Math.round((processed / totalChecked) * 100) : 100
  const ring = `conic-gradient(#38bdf8 ${quality * 3.6}deg, rgba(30,41,59,0.9) 0deg)`

  return (
    <div className="rounded-[28px] border border-blue-300/12 bg-slate-900/68 p-6 shadow-2xl shadow-slate-950/30 backdrop-blur-xl">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-black tracking-tight text-white">Quality</h2>
          <p className="mt-1 text-[14.7px] text-slate-500">Extraction history - {training.trainedCount || processed} documents processed</p>
        </div>
        <span className="rounded-full border border-cyan-300/20 bg-cyan-400/10 px-3 py-1 text-[11.6px] font-bold uppercase tracking-[0.14em] text-cyan-200">Live</span>
      </div>

      <div className="mt-8 flex items-center gap-6">
        <div className="grid h-32 w-32 shrink-0 place-items-center rounded-full p-2" style={{ background: ring }}>
          <div className="grid h-full w-full place-items-center rounded-full border border-white/8 bg-slate-950">
            <div className="text-center">
              <p className="text-3xl font-black text-white">{quality}%</p>
              <p className="text-[12.6px] font-bold uppercase tracking-[0.18em] text-slate-500">Status</p>
            </div>
          </div>
        </div>

        <div className="min-w-0 flex-1 space-y-3">
          {[
            ['Processed documents', processed],
            ['Failed documents', failed],
            ['User-corrected records', training.correctedCount || 0],
          ].map(([label, value]) => (
            <div key={label} className="flex items-center justify-between gap-3 rounded-2xl border border-white/8 bg-white/[0.035] px-3 py-2">
              <span className="flex items-center gap-2 text-[14.7px] text-slate-300">
                <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_14px_rgba(52,211,153,0.8)]" />
                {label}
              </span>
              <span className="text-[14.7px] font-black text-white">{value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function FeatureCard({ feature, index }) {
  const colors = ['text-blue-200', 'text-cyan-200', 'text-violet-200', 'text-emerald-200', 'text-amber-200', 'text-sky-200']

  return (
    <div className="group rounded-2xl border border-blue-300/10 bg-slate-900/62 p-5 shadow-xl shadow-slate-950/20 backdrop-blur-xl transition-all hover:-translate-y-1 hover:border-blue-300/25 hover:bg-slate-900/80">
      <span className={`mb-4 grid h-12 w-12 place-items-center rounded-2xl border border-white/10 bg-white/[0.045] text-[12.6px] font-black ${colors[index % colors.length]}`}>
        {feature.icon}
      </span>
      <h3 className="text-base font-black text-white">{feature.title}</h3>
      <p className="mt-2 text-[14.7px] leading-6 text-slate-500">{feature.desc}</p>
    </div>
  )
}

// Native <input type="date"> gives back YYYY-MM-DD; the app stores/searches
// dates as DD/MM/YYYY everywhere else, so convert before it ever leaves this form.
function isoDateToDDMMYYYY(iso) {
  if (!iso) return ''
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y}`
}

function DocumentSearchBar() {
  const navigate = useNavigate()
  const [number, setNumber] = useState('')
  const [date, setDate] = useState('')

  function handleSearch() {
    const params = new URLSearchParams()
    if (number.trim()) params.set('number', number.trim())
    if (date) params.set('date', isoDateToDDMMYYYY(date))
    const query = params.toString()
    navigate(query ? `/documents?${query}` : '/documents')
  }

  return (
    <section className="mt-5 rounded-[28px] border border-blue-300/12 bg-slate-900/68 p-5 shadow-2xl shadow-slate-950/30 backdrop-blur-xl sm:p-6">
      <h2 className="text-lg font-black text-white">Search Documents</h2>
      <p className="mt-1 text-[14.7px] text-slate-500">Find a document by number or date - opens the results in My Documents.</p>
      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label className="mb-2 block text-[12.6px] font-bold uppercase tracking-[0.1em] text-blue-300">Number</label>
          <input
            type="text"
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="e.g. 820268362"
            className="w-full rounded-2xl border border-white/10 bg-white/[0.045] px-4 py-3 text-[14.7px] text-white placeholder:text-slate-600 transition-colors focus:border-blue-300/40 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-2 block text-[12.6px] font-bold uppercase tracking-[0.1em] text-blue-300">Date</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="[color-scheme:dark] rounded-2xl border border-white/10 bg-white/[0.045] px-4 py-3 text-[14.7px] text-white transition-colors focus:border-blue-300/40 focus:outline-none"
          />
        </div>
        <button
          onClick={handleSearch}
          className="inline-flex items-center justify-center rounded-2xl bg-gradient-to-r from-blue-600 to-cyan-500 px-6 py-3 text-[14.7px] font-black text-white shadow-[0_18px_45px_rgba(37,99,235,0.3)] transition-all hover:-translate-y-0.5 hover:shadow-[0_22px_60px_rgba(37,99,235,0.42)]"
        >
          Search
        </button>
      </div>
    </section>
  )
}

export default function Dashboard() {
  const [exporting, setExporting] = useState(false)
  const { data, isLoading: docsLoading } = useDocumentsList({})
  const { data: training = { trainedCount: 0, correctedCount: 0 }, isLoading: trainingLoading } = useTrainingStats()
  const loading = docsLoading || trainingLoading

  const docs = data?.documents || []
  const byDocumentType = data?.byDocumentType || {}
  const stats = {
    total: docs.length,
    processed: docs.filter((d) => d.uploadStatus === 'processed').length,
    failed: docs.filter((d) => d.uploadStatus === 'failed').length,
    processedToday: docs.filter((d) => d.uploadStatus === 'processed' && isTodayIST(d.processedAt || d.reprocessedAt || d.updatedAt)).length,
    taxInvoice: byDocumentType['Tax Invoice'] || 0,
    deliveryChallan: byDocumentType['Delivery Challan'] || 0,
  }
  const recentDocs = docs.slice(0, 3)

  async function handleExport() {
    setExporting(true)
    try {
      await downloadWorkbook()
    } catch (err) {
      toast.error(err.userMessage || 'Could not download the Excel workbook. Please try again.')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="relative min-h-full overflow-hidden bg-[#020817]">
      <PageBackground variant="grid" />

      <main className="relative mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-10">
        <section className="grid items-center gap-7 rounded-[28px] border border-blue-300/12 bg-slate-900/58 p-5 shadow-[0_32px_110px_rgba(2,8,23,0.48)] backdrop-blur-xl sm:p-7 lg:grid-cols-[1.02fr_0.98fr] lg:p-8">
          <div className="max-w-3xl">
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-blue-300/20 bg-blue-500/10 px-4 py-2 text-[12.6px] font-bold uppercase tracking-[0.18em] text-blue-200">
              <span className="h-2 w-2 rounded-full bg-cyan-300 shadow-[0_0_18px_rgba(103,232,249,0.9)]" />
              AI-Powered Acknowledgement Intelligence
            </div>
            <h1 className="text-4xl font-black leading-[1.07] tracking-[-0.04em] text-white sm:text-5xl xl:text-[56px]">
              Extract. Verify. Export.
              <span className="block">Acknowledgements in <span className="text-blue-400 drop-shadow-[0_0_28px_rgba(59,130,246,0.55)]">seconds.</span></span>
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-slate-400">
              Upload Tax Invoice or Delivery Challan acknowledgements and let AI extract the document number and date instantly - then export everything to Excel.
            </p>
            <div className="mt-7 flex flex-col gap-3 sm:flex-row sm:flex-wrap">
              <Link
                to="/upload"
                className="inline-flex items-center justify-center rounded-2xl bg-gradient-to-r from-blue-600 to-cyan-500 px-6 py-3.5 text-[14.7px] font-black text-white no-underline shadow-[0_18px_45px_rgba(37,99,235,0.34)] transition-all hover:-translate-y-0.5 hover:shadow-[0_22px_60px_rgba(37,99,235,0.45)] focus:outline-none focus:ring-2 focus:ring-blue-300/60"
              >
                Upload Document
              </Link>
              <button
                onClick={handleExport}
                disabled={exporting}
                className="inline-flex items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-emerald-600 to-emerald-500 px-6 py-3.5 text-[14.7px] font-black text-white shadow-[0_18px_45px_rgba(16,185,129,0.34)] transition-all hover:-translate-y-0.5 hover:shadow-[0_22px_60px_rgba(16,185,129,0.45)] disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-emerald-300/60"
              >
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                  <path d="M12 4v12" />
                  <path d="M7 11l5 5 5-5" />
                  <path d="M4 20h16" />
                </svg>
                {exporting ? 'Exporting...' : 'Export Excel'}
              </button>
              <Link
                to="/documents"
                className="inline-flex items-center justify-center rounded-2xl border border-white/10 bg-white/[0.045] px-6 py-3.5 text-[14.7px] font-black text-slate-200 no-underline transition-all hover:-translate-y-0.5 hover:border-blue-300/30 hover:bg-blue-500/10 focus:outline-none focus:ring-2 focus:ring-blue-300/40"
              >
                My Documents
              </Link>
            </div>
          </div>

          <HeroIllustration />
        </section>

        <DocumentSearchBar />

        {loading ? (
          <section className="mt-6 rounded-[28px] border border-blue-300/12 bg-slate-900/68 shadow-2xl shadow-slate-950/30 backdrop-blur-xl">
            <LoadingState message="Loading dashboard..." />
          </section>
        ) : (
          <>
            <section className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <StatCard icon="TD" label="Total Documents" value={stats.total} helper="Acknowledgements in workspace" color="blue" />
              <StatCard icon="OK" label="Processed" value={stats.processed} helper="Ready for review" color="green" />
              <StatCard icon="ER" label="Failed" value={stats.failed} helper="Needs reprocess or review" color="red" />
              <StatCard icon="24" label="Processed Today" value={stats.processedToday} helper="Completed in today's run" color="violet" />
              <StatCard icon="TI" label="Tax Invoice" value={stats.taxInvoice} helper="Documents of this type" color="amber" />
              <StatCard icon="DC" label="Delivery Challan" value={stats.deliveryChallan} helper="Documents of this type" color="cyan" />
            </section>

            <section className="mt-6 grid gap-6 lg:grid-cols-[1.12fr_0.88fr]">
              <div className="rounded-[28px] border border-blue-300/12 bg-slate-900/68 p-5 shadow-2xl shadow-slate-950/30 backdrop-blur-xl sm:p-6">
                <div className="mb-5 flex items-center justify-between gap-3">
                  <div>
                    <h2 className="text-xl font-black tracking-tight text-white">Recent Documents</h2>
                    <p className="mt-1 text-[14.7px] text-slate-500">Latest acknowledgements processed by AckIntel AI</p>
                  </div>
                  <Link to="/documents" className="shrink-0 rounded-full border border-blue-300/20 bg-blue-500/10 px-4 py-2 text-[12.6px] font-black uppercase tracking-[0.14em] text-blue-200 no-underline transition-colors hover:bg-blue-500/15">
                    View all
                  </Link>
                </div>

                {recentDocs.length > 0 ? (
                  <div className="space-y-3">
                    {recentDocs.map((doc) => (
                      <RecentDocumentRow key={doc._id} doc={doc} />
                    ))}
                  </div>
                ) : (
                  <div className="rounded-2xl border border-dashed border-blue-300/14 bg-white/[0.025] px-5 py-10 text-center">
                    <p className="text-[14.7px] font-bold text-slate-300">No documents uploaded yet.</p>
                    <p className="mt-2 text-[14.7px] text-slate-500">Upload an acknowledgement to see recent document activity here.</p>
                  </div>
                )}
              </div>

              <QualityPanel stats={stats} training={training} />
            </section>
          </>
        )}

        <section className="mt-10">
          <div className="mb-5 flex items-end justify-between gap-4">
            <div>
              <p className="text-[12.6px] font-black uppercase tracking-[0.22em] text-blue-300/80">Capabilities</p>
              <h2 className="mt-2 text-2xl font-black tracking-tight text-white">What AckIntel AI does</h2>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {features.map((feature, index) => (
              <FeatureCard key={feature.title} feature={feature} index={index} />
            ))}
          </div>
        </section>

        <section className="mt-6 rounded-[28px] border border-blue-300/12 bg-slate-900/68 p-5 shadow-2xl shadow-slate-950/25 backdrop-blur-xl sm:p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-start gap-4">
              <span className="grid h-12 w-12 place-items-center rounded-2xl border border-blue-300/15 bg-blue-500/10 text-[12.6px] font-black text-blue-200">DOC</span>
              <div>
                <h2 className="text-lg font-black text-white">Supported Document Types</h2>
                <p className="mt-1 text-[14.7px] text-slate-500">Focused intake for acknowledgement processing.</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {supportedTypes.map((type) => (
                <span key={type} className="rounded-full border border-white/10 bg-white/[0.045] px-3 py-1.5 text-[12.6px] font-bold text-slate-300">
                  {type}
                </span>
              ))}
            </div>
          </div>
        </section>

        <section className="mt-6 rounded-[28px] border border-amber-300/12 bg-slate-900/68 p-5 shadow-2xl shadow-slate-950/25 backdrop-blur-xl sm:p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-start gap-4">
              <span className="grid h-12 w-12 place-items-center rounded-2xl border border-amber-300/15 bg-amber-500/10 text-[12.6px] font-black text-amber-200">SP</span>
              <div>
                <h2 className="text-lg font-black text-white">Free Up Space</h2>
                <p className="mt-1 max-w-xl text-[14.7px] text-slate-500">
                  Permanently remove original uploaded files you no longer need - extracted Number/Date data stays fully intact. Open a document from My Documents and use "Free Up Space" there.
                </p>
              </div>
            </div>
            <Link
              to="/documents"
              className="inline-flex shrink-0 items-center justify-center rounded-2xl border border-amber-300/25 bg-amber-500/10 px-5 py-3 text-[14.7px] font-black text-amber-200 no-underline transition-all hover:-translate-y-0.5 hover:bg-amber-500/15"
            >
              Manage My Documents
            </Link>
          </div>
        </section>
      </main>
    </div>
  )
}
