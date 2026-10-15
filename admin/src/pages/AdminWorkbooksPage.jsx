import { useEffect, useState } from 'react'
import api from '../utils/api'
import Banner from '../components/Banner'
import BackButton from '../components/BackButton'
import { Badge, Card, DataTable, EmptyState, ErrorState, PageHeader } from '../components/ui'
import { OwnerCell, TableSkeleton } from '../components/pageparts'

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
  const [loadError, setLoadError] = useState('')
  const [success, setSuccess] = useState('')
  const [busyId, setBusyId] = useState(null)

  function load() {
    setLoading(true)
    setLoadError('')
    return api.get('/admin/workbooks')
      .then((res) => setWorkbooks(res.data.workbooks || []))
      .catch((err) => setLoadError(err.userMessage || 'Could not load workbooks.'))
      .finally(() => setLoading(false))
  }

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load() }, [])

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
    <div className="mx-auto max-w-[1560px] px-4 py-6 sm:px-6 lg:px-8">
      <BackButton fallback="/" />
      <PageHeader
        title="Workbooks"
        subtitle={loading ? 'Loading...' : `${workbooks.length} workbook${workbooks.length !== 1 ? 's' : ''} across all users`}
      />

      <Banner error={error} success={success} />

      <Card className="overflow-hidden">
        {loading ? (
          <TableSkeleton />
        ) : loadError ? (
          <ErrorState message={loadError} onRetry={load} />
        ) : workbooks.length === 0 ? (
          <EmptyState title="No workbooks yet" hint="Excel workbooks created by users will show up here." />
        ) : (
          <DataTable minWidth={720}>
            <thead>
              <tr>
                <th>Owner</th>
                <th>Filename</th>
                <th>Year</th>
                <th>Status</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {workbooks.map((wb) => (
                <tr key={wb.id}>
                  <td><OwnerCell owner={wb.owner} /></td>
                  <td className="max-w-[280px] truncate text-slate-200" title={wb.filename}>{wb.filename}</td>
                  <td className="whitespace-nowrap text-[var(--muted)]">{wb.year}</td>
                  <td>
                    <Badge tone={wb.isActive ? 'green' : 'neutral'} dot>{wb.isActive ? 'Active' : 'Archived'}</Badge>
                  </td>
                  <td className="text-right">
                    <button
                      disabled={busyId === wb.id}
                      onClick={() => handleDownload(wb)}
                      className="btn btn-ghost btn-sm"
                    >
                      {busyId === wb.id ? 'Downloading...' : 'Download'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Card>
    </div>
  )
}
