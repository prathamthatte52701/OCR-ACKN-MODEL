import { useEffect, useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import api from '../utils/api'
import PaginationControls from '../components/PaginationControls'
import Banner from '../components/Banner'
import Modal from '../components/Modal'
import ConfirmModal from '../components/ConfirmModal'

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
      <h2 className="mb-1 text-lg font-black text-white">Edit document</h2>
      <p className="mb-4 text-[12.6px] text-slate-500">{doc.documentType} - owned by {doc.owner?.username || 'unknown'}</p>
      <div className="space-y-4">
        {fields.map((f, idx) => (
          <div key={f.key}>
            <label className="mb-1 block text-[12.6px] font-semibold text-slate-400">{f.label}</label>
            <div className="flex gap-2">
              <input
                autoFocus={idx === 0}
                value={values[f.key]}
                onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                onKeyDown={(e) => e.key === 'Enter' && saveField(f.key)}
                className="w-full rounded-xl border border-white/10 bg-slate-950/60 px-3.5 py-2.5 text-[14.7px] text-white outline-none focus:border-emerald-300/60"
              />
              <button
                onClick={() => saveField(f.key)}
                disabled={savingField === f.key}
                className="shrink-0 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-500 px-3.5 py-2.5 text-[13.6px] font-black text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                {savingField === f.key ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        ))}
      </div>
      <Banner error={error} />
      <button type="button" onClick={onClose} className="mt-4 w-full rounded-xl border border-white/10 bg-white/[0.035] px-4 py-2.5 text-[14.7px] font-bold text-slate-300 hover:border-white/20">
        Close
      </button>
    </Modal>
  )
}

function statusBadge(status) {
  const map = {
    processed: 'border-emerald-300/25 bg-emerald-500/10 text-emerald-200',
    failed: 'border-rose-400/25 bg-rose-500/10 text-rose-200',
    uploaded: 'border-amber-300/25 bg-amber-500/10 text-amber-200',
  }
  return map[status] || 'border-white/10 bg-white/5 text-slate-400'
}

export default function AdminDocumentsPage() {
  const [documents, setDocuments] = useState([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [totalDocuments, setTotalDocuments] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [editingDoc, setEditingDoc] = useState(null)
  const [deletingDoc, setDeletingDoc] = useState(null)
  const [purgingDoc, setPurgingDoc] = useState(null)
  const [busyId, setBusyId] = useState(null)

  async function load(pageToLoad = page) {
    setLoading(true)
    setError('')
    try {
      const res = await api.get('/admin/documents', { params: { page: pageToLoad, limit: PAGE_SIZE } })
      setDocuments(res.data.documents || [])
      setTotalPages(res.data.totalPages || 1)
      setTotalDocuments(res.data.totalDocuments || 0)
    } catch (err) {
      setError(err.userMessage || 'Could not load documents.')
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
      await api.delete(`/admin/documents/${doc._id}`)
      setSuccess('Document deleted.')
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
    <main className="mx-auto max-w-[1280px] px-4 py-8 sm:px-6 lg:px-10">
      <h1 className="mb-1 text-3xl font-black tracking-tight text-white">Documents</h1>
      <p className="mb-6 text-[14.7px] text-slate-500">{loading ? 'Loading...' : `${totalDocuments} document${totalDocuments !== 1 ? 's' : ''} across all users`}</p>

      <Banner error={error} success={success} />

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-transparent border-t-emerald-400" />
        </div>
      ) : (
        <div className="overflow-x-auto rounded-[24px] border border-emerald-300/12 bg-slate-900/60">
          <table className="w-full text-left text-[13.6px]">
            <thead>
              <tr className="border-b border-white/8 text-[11.6px] font-black uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3">Owner</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Number</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((d) => (
                <tr key={d._id} className="border-b border-white/5 last:border-0">
                  <td className="px-4 py-3">
                    <div className="font-bold text-white">{d.owner?.username || 'unknown'}</div>
                    <div className="text-[11.6px] text-slate-500">{d.owner?.email}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-300">
                    {d.documentType}
                    {d.filePurged && (
                      <span className="ml-2 rounded-full border border-amber-300/25 bg-amber-500/10 px-2 py-0.5 text-[10.5px] font-black uppercase text-amber-200">File removed</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-300">{docNumber(d)}</td>
                  <td className="px-4 py-3 text-slate-400">{d.date || '-'}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full border px-2.5 py-1 text-[11.6px] font-black uppercase ${statusBadge(d.uploadStatus)}`}>
                      {d.uploadStatus}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <button onClick={() => setEditingDoc(d)} className="rounded-full border border-white/10 bg-white/[0.035] px-3 py-1.5 text-[11.6px] font-bold text-slate-300 hover:border-emerald-300/30">
                        Edit
                      </button>
                      {!d.filePurged && (
                        <button disabled={busyId === d._id} onClick={() => setPurgingDoc(d)} className="rounded-full border border-white/10 bg-white/[0.035] px-3 py-1.5 text-[11.6px] font-bold text-amber-300 hover:border-amber-300/30 hover:bg-amber-500/10 disabled:opacity-50">
                          Free Space
                        </button>
                      )}
                      <button disabled={busyId === d._id} onClick={() => setDeletingDoc(d)} className="rounded-full border border-white/10 bg-white/[0.035] px-3 py-1.5 text-[11.6px] font-bold text-rose-300 hover:border-rose-300/30 hover:bg-rose-500/10 disabled:opacity-50">
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

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
            title="Delete this document?"
            message={`Delete this ${deletingDoc.documentType} document owned by ${deletingDoc.owner?.username || 'unknown'}? This cannot be undone.`}
            onConfirm={() => deleteDoc(deletingDoc)}
            onClose={() => setDeletingDoc(null)}
            busy={busyId === deletingDoc._id}
            strong
          />
        )}
        {purgingDoc && (
          <ConfirmModal
            title="Permanently remove the original file?"
            message={`This will permanently delete the original uploaded file for this ${purgingDoc.documentType} document owned by ${purgingDoc.owner?.username || 'unknown'}. The extracted Number/Date data will NOT be affected and will remain fully accessible. This cannot be undone.`}
            confirmLabel="Yes, Permanently Remove File"
            onConfirm={() => purgeDocFile(purgingDoc)}
            onClose={() => setPurgingDoc(null)}
            busy={busyId === purgingDoc._id}
            strong
          />
        )}
      </AnimatePresence>
    </main>
  )
}
