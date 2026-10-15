import { useEffect, useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import api from '../utils/api'
import PaginationControls from '../components/PaginationControls'
import Banner from '../components/Banner'
import Modal from '../components/Modal'
import ConfirmModal from '../components/ConfirmModal'
import BackButton from '../components/BackButton'
import { Badge, Card, DataTable, EmptyState, ErrorState, PageHeader } from '../components/ui'
import { OwnerCell, TableSkeleton } from '../components/pageparts'
import { statusTone } from '../utils/status'

const PAGE_SIZE = 30

const FIELDS_BY_TYPE = {
  'Tax Invoice': [
    { key: 'taxInvoiceNo', label: 'Tax Invoice No.' },
    { key: 'referenceNo', label: 'Reference No.' },
    { key: 'date', label: 'Date' },
  ],
  'Delivery Challan': [
    { key: 'number', label: 'Number' },
    { key: 'date', label: 'Date' },
  ],
}

function EditDocumentModal({ doc, onClose, onSaved }) {
  const fields = FIELDS_BY_TYPE[doc.documentType] || []
  const [values, setValues] = useState(() => Object.fromEntries(fields.map((f) => [f.key, doc[f.key] || ''])))
  const [savingField, setSavingField] = useState(null)
  const [error, setError] = useState('')

  async function saveField(key) {
    setError('')
    if (!values[key] || !values[key].trim()) { setError('Please enter a value before saving.'); return }
    setSavingField(key)
    try {
      const res = await api.patch(`/admin/documents/${doc._id}`, { field: key, value: values[key] })
      onSaved(res.data.document, `${key} updated.`)
    } catch (err) {
      setError(err.userMessage || 'Could not save field.')
    } finally {
      setSavingField(null)
    }
  }

  return (
    <Modal onClose={onClose}>
      <h2 className="mb-1 text-lg font-extrabold text-white">Edit document</h2>
      <p className="mb-4 truncate text-[13px] text-[var(--muted)]" title={`${doc.documentType} - owned by ${doc.owner?.username || 'unknown'}`}>{doc.documentType} - owned by {doc.owner?.username || 'unknown'}</p>
      <div className="space-y-4">
        {fields.map((f, idx) => (
          <div key={f.key}>
            <label htmlFor={`edit-${f.key}`} className="ui-label mb-1 block">{f.label}</label>
            <div className="flex gap-2">
              <input
                id={`edit-${f.key}`}
                autoFocus={idx === 0}
                value={values[f.key]}
                onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                onKeyDown={(e) => e.key === 'Enter' && saveField(f.key)}
                className="input"
              />
              <button
                onClick={() => saveField(f.key)}
                disabled={savingField === f.key}
                className="btn btn-primary shrink-0"
              >
                {savingField === f.key ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        ))}
      </div>
      <Banner error={error} />
      <button type="button" onClick={onClose} className="btn btn-ghost mt-4 w-full">
        Close
      </button>
    </Modal>
  )
}

export default function AdminDocumentsPage() {
  const [documents, setDocuments] = useState([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [totalDocuments, setTotalDocuments] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [success, setSuccess] = useState('')
  const [editingDoc, setEditingDoc] = useState(null)
  const [deletingDoc, setDeletingDoc] = useState(null)
  const [purgingDoc, setPurgingDoc] = useState(null)
  const [busyId, setBusyId] = useState(null)

  async function load(pageToLoad = page) {
    setLoading(true)
    setLoadError('')
    try {
      const res = await api.get('/admin/documents', { params: { page: pageToLoad, limit: PAGE_SIZE } })
      setDocuments(res.data.documents || [])
      setTotalPages(res.data.totalPages || 1)
      setTotalDocuments(res.data.totalDocuments || 0)
    } catch (err) {
      setLoadError(err.userMessage || 'Could not load documents.')
    } finally {
      setLoading(false)
    }
  }

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { load(page) }, [page])

  async function deleteDoc(doc) {
    setBusyId(doc._id)
    setError('')
    setSuccess('')
    try {
      const res = await api.delete(`/admin/documents/${doc._id}`)
      if (res.data.gridFsCleanupFailed) {
        setError(res.data.message || 'Document was permanently deleted, but the file cleanup failed - see Orphaned Files.')
      } else {
        setSuccess(res.data.message || 'Document permanently deleted.')
      }
      setDeletingDoc(null)
      load(page)
    } catch (err) {
      setError(err.userMessage || 'Could not delete document.')
      setDeletingDoc(null)
    } finally {
      setBusyId(null)
    }
  }

  async function purgeDocFile(doc) {
    setBusyId(doc._id)
    setError('')
    setSuccess('')
    try {
      const res = await api.post(`/admin/documents/${doc._id}/purge-file`)
      if (res.data.gridFsCleanupFailed) {
        setError(res.data.message || 'Document data was removed, but the file cleanup failed - see Orphaned Files.')
      } else {
        setSuccess(res.data.message || 'Original file removed.')
      }
      setPurgingDoc(null)
      load(page)
    } catch (err) {
      setError(err.userMessage || 'Could not remove the original file.')
      setPurgingDoc(null)
    } finally {
      setBusyId(null)
    }
  }

  function docNumber(doc) {
    if (doc.documentType === 'Tax Invoice') return [doc.taxInvoiceNo, doc.referenceNo].filter(Boolean).join(' / ') || '-'
    return doc.number || '-'
  }

  return (
    <div className="mx-auto max-w-[1560px] px-4 py-6 sm:px-6 lg:px-8">
      <BackButton fallback="/" />
      <PageHeader
        title="Documents"
        subtitle={loading ? 'Loading...' : `${totalDocuments} document${totalDocuments !== 1 ? 's' : ''} across all users`}
      />

      <Banner error={error} success={success} />

      <Card className="overflow-hidden">
        {loading ? (
          <TableSkeleton />
        ) : loadError ? (
          <ErrorState message={loadError} onRetry={() => load(page)} />
        ) : documents.length === 0 ? (
          <EmptyState title="No documents yet" hint="Documents uploaded by users will show up here." />
        ) : (
          <DataTable minWidth={900}>
            <thead>
              <tr>
                <th>Owner</th>
                <th>Type</th>
                <th>Number</th>
                <th>Date</th>
                <th>Status</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((d) => (
                <tr key={d._id}>
                  <td><OwnerCell owner={d.owner} /></td>
                  <td>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-slate-200">{d.documentType}</span>
                      {d.filePurged && <Badge tone="amber">File removed</Badge>}
                    </div>
                  </td>
                  <td className="max-w-[220px] truncate text-slate-200" title={docNumber(d)}>{docNumber(d)}</td>
                  <td className="whitespace-nowrap text-[var(--muted)]">{d.date || '-'}</td>
                  <td>
                    <Badge tone={statusTone(d.uploadStatus)} dot className="capitalize">{d.uploadStatus}</Badge>
                  </td>
                  <td>
                    <div className="flex flex-wrap justify-end gap-2">
                      <button onClick={() => setEditingDoc(d)} className="btn btn-ghost btn-sm">
                        Edit
                      </button>
                      {!d.filePurged && (
                        <button disabled={busyId === d._id} onClick={() => setPurgingDoc(d)} className="btn btn-ghost btn-sm" style={{ color: 'var(--amber)', borderColor: 'rgba(251,191,36,.45)' }}>
                          File Delete
                        </button>
                      )}
                      <button disabled={busyId === d._id} onClick={() => setDeletingDoc(d)} className="btn btn-danger btn-sm">
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Card>

      <PaginationControls page={page} totalPages={totalPages} onChange={setPage} />

      <AnimatePresence>
        {editingDoc && (
          <EditDocumentModal
            doc={editingDoc}
            onClose={() => setEditingDoc(null)}
            onSaved={(updated, message) => {
              setDocuments((prev) => prev.map((d) => (d._id === updated._id ? { ...updated, owner: d.owner } : d)))
              setEditingDoc((prev) => ({ ...updated, owner: prev.owner }))
              setSuccess(message)
            }}
          />
        )}
        {deletingDoc && (
          <ConfirmModal
            title="Permanently delete this document?"
            message={`This will PERMANENTLY delete this ${deletingDoc.documentType} document owned by ${deletingDoc.owner?.username || 'unknown'} - both the original file and all its extracted data. This cannot be undone and there is no recovery path.`}
            confirmLabel="Yes, Delete Permanently"
            onConfirm={() => deleteDoc(deletingDoc)}
            onClose={() => setDeletingDoc(null)}
            busy={busyId === deletingDoc._id}
            strong
          />
        )}
        {purgingDoc && (
          <ConfirmModal
            title="File Delete - permanently remove the original file?"
            message={`This will permanently delete the original uploaded file for this ${purgingDoc.documentType} document owned by ${purgingDoc.owner?.username || 'unknown'}. The extracted Number/Date data will NOT be affected and will remain fully accessible. This cannot be undone.`}
            confirmLabel="Yes, File Delete"
            onConfirm={() => purgeDocFile(purgingDoc)}
            onClose={() => setPurgingDoc(null)}
            busy={busyId === purgingDoc._id}
            strong
          />
        )}
      </AnimatePresence>
    </div>
  )
}
