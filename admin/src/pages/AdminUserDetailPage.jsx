import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import api from '../utils/api'
import PaginationControls from '../components/PaginationControls'
import Banner from '../components/Banner'
import { formatIST } from '../utils/formatDate'

const SECTION_PAGE_SIZE = 10

function statusBadge(status) {
  const map = {
    processed: 'border-emerald-300/25 bg-emerald-500/10 text-emerald-200',
    failed: 'border-rose-400/25 bg-rose-500/10 text-rose-200',
    uploaded: 'border-amber-300/25 bg-amber-500/10 text-amber-200',
  }
  return map[status] || 'border-white/10 bg-white/5 text-slate-400'
}

function docNumber(doc) {
  if (doc.documentType === 'Tax Invoice') return [doc.taxInvoiceNo, doc.referenceNo].filter(Boolean).join(' / ') || '-'
  return doc.number || '-'
}

function exportNumber(row) {
  if (row.documentType === 'Tax Invoice') return [row.taxInvoiceNo, row.referenceNo].filter(Boolean).join(' / ') || '-'
  return row.number || '-'
}

function Section({ title, count, page, totalPages, onPageChange, children }) {
  return (
    <section className="mb-8">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-lg font-black text-white">{title}</h2>
        <span className="text-[12.6px] font-bold text-slate-500">{count} total</span>
      </div>
      <div className="overflow-x-auto rounded-[24px] border border-emerald-300/12 bg-slate-900/60">
        {children}
      </div>
      <PaginationControls page={page} totalPages={totalPages} onChange={onPageChange} />
    </section>
  )
}

export default function AdminUserDetailPage() {
  const { id } = useParams()
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [documents, setDocuments] = useState([])
  const [docPage, setDocPage] = useState(1)
  const [docTotalPages, setDocTotalPages] = useState(1)
  const [docTotal, setDocTotal] = useState(0)

  const [exports, setExports] = useState([])
  const [expPage, setExpPage] = useState(1)
  const [expTotalPages, setExpTotalPages] = useState(1)
  const [expTotal, setExpTotal] = useState(0)

  const [logs, setLogs] = useState([])
  const [logPage, setLogPage] = useState(1)
  const [logTotalPages, setLogTotalPages] = useState(1)
  const [logTotal, setLogTotal] = useState(0)

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- standard fetch-on-mount pattern
    setLoading(true)
    setError('')
    api.get(`/admin/users/${id}`)
      .then((res) => setUser(res.data.user))
      .catch((err) => setError(err.userMessage || 'Could not load user.'))
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => {
    api.get('/admin/documents', { params: { userId: id, page: docPage, limit: SECTION_PAGE_SIZE } })
      .then((res) => {
        setDocuments(res.data.documents || [])
        setDocTotalPages(res.data.totalPages || 1)
        setDocTotal(res.data.totalDocuments || 0)
      })
      .catch(() => {})
  }, [id, docPage])

  useEffect(() => {
    api.get('/admin/exports', { params: { userId: id, page: expPage, limit: SECTION_PAGE_SIZE } })
      .then((res) => {
        setExports(res.data.exports || [])
        setExpTotalPages(res.data.totalPages || 1)
        setExpTotal(res.data.totalExports || 0)
      })
      .catch(() => {})
  }, [id, expPage])

  useEffect(() => {
    api.get('/admin/logs', { params: { userId: id, page: logPage, limit: SECTION_PAGE_SIZE } })
      .then((res) => {
        setLogs(res.data.logs || [])
        setLogTotalPages(res.data.totalPages || 1)
        setLogTotal(res.data.totalLogs || 0)
      })
      .catch(() => {})
  }, [id, logPage])

  if (loading) {
    return (
      <main className="mx-auto max-w-[1280px] px-4 py-8 sm:px-6 lg:px-10">
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-transparent border-t-emerald-400" />
        </div>
      </main>
    )
  }

  return (
    <main className="mx-auto max-w-[1280px] px-4 py-8 sm:px-6 lg:px-10">
      <Link to="/users" className="mb-4 inline-block text-[13.6px] font-bold text-slate-500 hover:text-emerald-300">&larr; Back to Users</Link>

      <Banner error={error} />

      {user && (
        <div className="mb-8 flex flex-wrap items-center justify-between gap-4 rounded-[24px] border border-emerald-300/12 bg-slate-900/60 p-6">
          <div>
            <h1 className="text-3xl font-black tracking-tight text-white">{user.username}</h1>
            <p className="mt-1 text-[14.7px] text-slate-500">{user.email}</p>
          </div>
          <div className="flex items-center gap-3">
            <span className={`rounded-full border px-2.5 py-1 text-[11.6px] font-black uppercase ${user.role === 'admin' ? 'border-emerald-300/25 bg-emerald-500/10 text-emerald-200' : 'border-white/10 bg-white/5 text-slate-400'}`}>
              {user.role}
            </span>
            <span className="text-[12.6px] text-slate-500">Joined {formatIST(user.createdAt)}</span>
          </div>
        </div>
      )}

      <Section title="Documents" count={docTotal} page={docPage} totalPages={docTotalPages} onPageChange={setDocPage}>
        <table className="w-full text-left text-[13.6px]">
          <thead>
            <tr className="border-b border-white/8 text-[11.6px] font-black uppercase tracking-wide text-slate-500">
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Number</th>
              <th className="px-4 py-3">Date</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Uploaded</th>
            </tr>
          </thead>
          <tbody>
            {documents.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-6 text-center text-slate-500">No documents.</td></tr>
            ) : documents.map((d) => (
              <tr key={d._id} className="border-b border-white/5 last:border-0">
                <td className="px-4 py-3 text-slate-300">{d.documentType}</td>
                <td className="px-4 py-3 text-slate-300">{docNumber(d)}</td>
                <td className="px-4 py-3 text-slate-400">{d.date || '-'}</td>
                <td className="px-4 py-3">
                  <span className={`rounded-full border px-2.5 py-1 text-[11.6px] font-black uppercase ${statusBadge(d.uploadStatus)}`}>
                    {d.uploadStatus}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-500">{formatIST(d.createdAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Export Activity" count={expTotal} page={expPage} totalPages={expTotalPages} onPageChange={setExpPage}>
        <table className="w-full text-left text-[13.6px]">
          <thead>
            <tr className="border-b border-white/8 text-[11.6px] font-black uppercase tracking-wide text-slate-500">
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Number</th>
              <th className="px-4 py-3">Date</th>
              <th className="px-4 py-3">Exported At</th>
              <th className="px-4 py-3">Workbook</th>
            </tr>
          </thead>
          <tbody>
            {exports.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-6 text-center text-slate-500">No exports.</td></tr>
            ) : exports.map((row) => (
              <tr key={row.id} className="border-b border-white/5 last:border-0">
                <td className="px-4 py-3 text-slate-300">{row.documentType}</td>
                <td className="px-4 py-3 text-slate-300">{exportNumber(row)}</td>
                <td className="px-4 py-3 text-slate-400">{row.date || '-'}</td>
                <td className="px-4 py-3 text-slate-500">{formatIST(row.exportedAt)}</td>
                <td className="px-4 py-3 text-slate-300">{row.workbook?.filename || <span className="text-slate-600">Unknown</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Activity Log" count={logTotal} page={logPage} totalPages={logTotalPages} onPageChange={setLogPage}>
        <table className="w-full text-left text-[13.6px]">
          <thead>
            <tr className="border-b border-white/8 text-[11.6px] font-black uppercase tracking-wide text-slate-500">
              <th className="px-4 py-3">Time</th>
              <th className="px-4 py-3">Action</th>
              <th className="px-4 py-3">Context</th>
            </tr>
          </thead>
          <tbody>
            {logs.length === 0 ? (
              <tr><td colSpan={3} className="px-4 py-6 text-center text-slate-500">No log entries.</td></tr>
            ) : logs.map((l) => (
              <tr key={l.id} className="border-b border-white/5 last:border-0">
                <td className="px-4 py-3 whitespace-nowrap text-slate-400">{formatIST(l.createdAt)}</td>
                <td className="px-4 py-3">
                  <span className="rounded-full border border-emerald-300/25 bg-emerald-500/10 px-2.5 py-1 text-[11.6px] font-black uppercase text-emerald-200">{l.action}</span>
                </td>
                <td className="px-4 py-3 max-w-[360px] truncate text-slate-500" title={JSON.stringify(l.context)}>
                  {JSON.stringify(l.context)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </main>
  )
}
