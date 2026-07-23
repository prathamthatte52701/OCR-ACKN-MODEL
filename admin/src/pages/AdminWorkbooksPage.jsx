import { useEffect, useState } from 'react'
import api from '../utils/api'
import Banner from '../components/Banner'

async function downloadWorkbook(id, filename) {
  let res
  try {
    res = await api.get(`/admin/workbooks/${id}/download`, { responseType: 'blob' })
  } catch (err) {
    // With responseType 'blob', a JSON error body arrives as a Blob too, not
    // parsed JSON - err.userMessage ends up undefined and the generic
    // "Something went wrong" shows instead of the real reason. Re-read the
    // blob as text and parse it here.
    let body
    if (err.response?.data instanceof Blob) {
      try { body = JSON.parse(await err.response.data.text()) } catch { body = null }
    } else {
      body = err.response?.data || null
    }
    throw Object.assign(err, {
      userMessage: (typeof body?.detail === 'string' && body.detail) || body?.detail?.message || err.userMessage,
    })
  }

  const url = window.URL.createObjectURL(new Blob([res.data]))
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => window.URL.revokeObjectURL(url), 1000)
}

export default function AdminWorkbooksPage() {
  const [workbooks, setWorkbooks] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [busyId, setBusyId] = useState(null)

  useEffect(() => {
    let cancelled = false
    api.get('/admin/workbooks')
      .then((res) => { if (!cancelled) setWorkbooks(res.data.workbooks || []) })
      .catch((err) => { if (!cancelled) setError(err.userMessage || 'Could not load workbooks.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  async function handleDownload(wb) {
    setBusyId(wb.id)
    setError('')
    setSuccess('')
    try {
      await downloadWorkbook(wb.id, wb.filename)
      setSuccess(`Downloaded ${wb.filename}.`)
    } catch (err) {
      setError(err.userMessage || 'Could not download workbook.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <main className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6 lg:px-10">
      <h1 className="mb-1 text-3xl font-black tracking-tight text-white">Workbooks</h1>
      <p className="mb-6 text-[14.7px] text-slate-500">{loading ? 'Loading...' : `${workbooks.length} workbook${workbooks.length !== 1 ? 's' : ''} across all users`}</p>

      <Banner error={error} success={success} />

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-transparent border-t-emerald-400" />
        </div>
      ) : workbooks.length === 0 ? (
        <div className="rounded-[24px] border border-emerald-300/12 bg-slate-900/60 p-10 text-center text-[14.7px] text-slate-500">
          No workbooks yet.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-[24px] border border-emerald-300/12 bg-slate-900/60">
          <table className="w-full text-left text-[13.6px]">
            <thead>
              <tr className="border-b border-white/8 text-[11.6px] font-black uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3">Owner</th>
                <th className="px-4 py-3">Filename</th>
                <th className="px-4 py-3">Year</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {workbooks.map((wb) => (
                <tr key={wb.id} className="border-b border-white/5 last:border-0">
                  <td className="px-4 py-3">
                    <div className="font-bold text-white">{wb.owner?.username || 'unknown'}</div>
                    <div className="text-[11.6px] text-slate-500">{wb.owner?.email}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-300">{wb.filename}</td>
                  <td className="px-4 py-3 text-slate-400">{wb.year}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full border px-2.5 py-1 text-[11.6px] font-black uppercase ${wb.isActive ? 'border-emerald-300/25 bg-emerald-500/10 text-emerald-200' : 'border-white/10 bg-white/5 text-slate-400'}`}>
                      {wb.isActive ? 'Active' : 'Archived'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      disabled={busyId === wb.id}
                      onClick={() => handleDownload(wb)}
                      className="rounded-full border border-white/10 bg-white/[0.035] px-3 py-1.5 text-[11.6px] font-bold text-slate-300 hover:border-emerald-300/30 disabled:opacity-50"
                    >
                      {busyId === wb.id ? 'Downloading...' : 'Download'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  )
}
