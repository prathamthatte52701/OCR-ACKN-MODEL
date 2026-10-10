import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { ArrowLeft, FileX } from 'lucide-react'
import { downloadDocument, fetchDocumentFile } from '../api/documents'
import { useDocument } from '../hooks/useDocumentsQueries'
import {
  useCorrectDocument,
  useReprocessDocument,
  useDeleteDocument,
  useSaveDocumentMutation,
  usePurgeDocumentFile,
} from '../hooks/useDocumentMutations'
import CorrectionModal from '../components/CorrectionModal'
import LazyDocumentViewer from '../components/LazyDocumentViewer'
import LoadingState from '../components/LoadingState'
import ErrorMessage from '../components/ErrorMessage'
import ProcessingState from '../components/ProcessingState'
import { formatIST } from '../utils/formatDate'
import { confirmAction } from '../store/dialogStore'

function formatSize(bytes) {
  if (!bytes) return '-'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

// Which fields are editable, per documentType - matches backend
// EDITABLE_FIELDS and PATCH /:id/correct's field-conditional validation.
function fieldsFor(doc) {
  if (doc.documentType === 'Tax Invoice') {
    return [
      { key: 'taxInvoiceNo', label: 'TAX INVOICE No.', value: doc.taxInvoiceNo },
      { key: 'referenceNo', label: 'Reference No.', value: doc.referenceNo },
      { key: 'date', label: 'Date', value: doc.date },
    ]
  }
  return [
    { key: 'number', label: 'Delivery Challan No.', value: doc.number },
    { key: 'date', label: 'Date', value: doc.date },
  ]
}

export default function DocumentDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { data: doc, isLoading, isError, error, refetch } = useDocument(id)
  const [editingField, setEditingField] = useState(null)
  const [reprocessMsg, setReprocessMsg] = useState('')
  const [deleting, setDeleting] = useState(false)

  const correctMutation = useCorrectDocument(id)
  const reprocessMutation = useReprocessDocument(id)
  const deleteMutation = useDeleteDocument(id)
  const saveMutation = useSaveDocumentMutation()
  const purgeMutation = usePurgeDocumentFile(id)

  // Original file for the in-page viewer. Short gcTime so big blobs do not linger; not stored anywhere else.
  const showFile = !!doc && !doc.filePurged
  const fileQuery = useQuery({
    queryKey: ['document-file', id],
    queryFn: () => fetchDocumentFile(id),
    enabled: showFile,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 5 * 60 * 1000,
    gcTime: 60 * 1000,
  })
  const blob = fileQuery.data
  const originalFilename = doc?.originalFilename
  const mimeType = doc?.mimeType
  const viewerFile = useMemo(
    () => (blob ? new File([blob], originalFilename || 'document', { type: mimeType || blob.type }) : null),
    [blob, originalFilename, mimeType],
  )

  async function handleCorrect(field, newValue) {
    try {
      await correctMutation.mutateAsync({ field: field.key, value: newValue })
      setEditingField(null)
      toast.success(`${field.label} updated successfully.`)
    } catch (err) {
      toast.error(err.userMessage || 'Could not save your correction. Please try again.')
    }
  }

  async function handleReprocess() {
    const ok = await confirmAction({
      title: 'Reprocess this document?',
      message: 'Re-run OCR and AI analysis on this document?',
      confirmLabel: 'Yes, Reprocess',
    })
    if (!ok) return
    setReprocessMsg('')
    try {
      await reprocessMutation.mutateAsync()
      setReprocessMsg('Reprocessing started. Check the document status shortly.')
    } catch (err) {
      setReprocessMsg(err.userMessage || 'Could not start reprocessing. Please try again.')
    }
  }

  async function handlePurgeFile() {
    const ok = await confirmAction({
      title: 'File Delete - permanently remove the original file?',
      message:
        'This will permanently delete the original uploaded file. The extracted Number/Date ' +
        'data will NOT be affected and will remain fully accessible. This cannot be undone.',
      confirmLabel: 'Yes, File Delete',
      danger: true,
    })
    if (!ok) return
    try {
      const result = await purgeMutation.mutateAsync()
      if (result.gridFsCleanupFailed) {
        toast.warning(
          result.message ||
            "Your document's data was removed, but we couldn't fully clean up the original " +
              'file due to a system issue. This has been flagged for admin review - no action ' +
              'needed from you.'
        )
      } else {
        toast.success(result.message || 'Original file permanently removed.')
      }
    } catch (err) {
      toast.error(err.userMessage || 'Could not remove the original file. Please try again.')
    }
  }

  async function handleSave() {
    if (doc.exported) {
      const ok = await confirmAction({
        title: 'Save again?',
        message: 'This document has already been saved to Excel. Save again?',
        confirmLabel: 'Yes, Save Again',
      })
      if (!ok) return
    }
    try {
      const message = await saveMutation.mutateAsync(id)
      if (message) toast.success(message)
    } catch (err) {
      toast.error(err.userMessage || 'Could not save this document to Excel. Please try again.')
    }
  }

  async function handleDelete() {
    const ok = await confirmAction({
      title: 'Permanently delete this document?',
      message:
        'This will PERMANENTLY delete this document - both the original file and all its ' +
        'extracted data. This cannot be undone and there is no recovery path.',
      confirmLabel: 'Yes, Delete Permanently',
      danger: true,
    })
    if (!ok) return
    setDeleting(true)
    try {
      const result = await deleteMutation.mutateAsync()
      if (result?.gridFsCleanupFailed) {
        toast.warning(
          result.message ||
            "This document was permanently deleted, but we couldn't fully clean up the " +
              'original file due to a system issue. This has been flagged for admin review.'
        )
      } else {
        toast.success(result?.message || 'Document permanently deleted.')
      }
      navigate('/documents')
    } catch (err) {
      toast.error(err.userMessage || 'Could not delete this document. Please try again.')
      setDeleting(false)
    }
  }

  async function handleDownload() {
    try {
      await downloadDocument(id, doc.originalFilename)
      toast.success('Original file downloaded.')
    } catch (err) {
      toast.error(err.userMessage || 'Could not download the original file. Please try again.')
    }
  }

  if (isLoading) return <div className="mx-auto max-w-4xl px-4 py-8"><LoadingState /></div>
  if (isError) return <div className="mx-auto max-w-4xl px-4 py-8"><ErrorMessage message={error?.userMessage || 'Document not found or could not be loaded.'} onRetry={refetch} /></div>
  if (!doc) return null

  const statusColor = {
    uploaded: 'text-yellow-400 bg-yellow-900/20 border-yellow-800',
    processed: 'text-green-400 bg-green-900/20 border-green-800',
    failed: 'text-red-400 bg-red-900/20 border-red-800',
  }[doc.uploadStatus] || 'text-gray-400 bg-gray-800 border-gray-700'

  const reprocessing = reprocessMutation.isPending

  return (
    <div className={`mx-auto px-4 py-8 ${doc.filePurged ? 'max-w-4xl' : 'max-w-6xl'}`}>
      <Link to="/documents" className="mb-4 flex items-center gap-1 text-[14.7px] text-gray-500 no-underline hover:text-gray-300">
        <ArrowLeft className="h-4 w-4" /> Back to Documents
      </Link>

      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">{doc.autoName}</h1>
          <p className="mt-0.5 text-[12.6px] text-gray-500">{doc.originalFilename}</p>
        </div>
        <span className={`rounded-full border px-2.5 py-1 text-[12.6px] font-medium capitalize ${statusColor}`}>
          {doc.uploadStatus}
        </span>
      </div>

      <div className="mb-5 grid grid-cols-2 gap-3 rounded-xl border border-gray-800 bg-gray-900 p-4 text-[14.7px] sm:grid-cols-4">
        {[
          { label: 'Document Type', value: doc.documentType || '-' },
          { label: 'File Size', value: formatSize(doc.size) },
          { label: 'Uploaded', value: formatIST(doc.createdAt) },
          { label: 'Processed', value: formatIST(doc.processedAt || doc.reprocessedAt) },
        ].map((m) => (
          <div key={m.label}>
            <p className="mb-0.5 text-[12.6px] text-gray-600">{m.label}</p>
            <p className="text-[14.7px] text-gray-300">{m.value}</p>
          </div>
        ))}
      </div>

      {doc.uploadStatus === 'failed' && (
        <div className="mb-5 rounded-xl border border-red-800 bg-red-900/20 p-4">
          <p className="mb-1 font-semibold text-red-400">Processing Failed</p>
          <p className="text-[14.7px] text-red-300/70">{doc.processingError || 'We could not process this document. Try reprocessing it below.'}</p>
        </div>
      )}

      {reprocessMsg && (
        <div className={`mb-4 rounded-xl border p-3 text-[14.7px] ${reprocessMsg.toLowerCase().includes('started') ? 'border-green-800 bg-green-900/20 text-green-400' : 'border-red-800 bg-red-900/20 text-red-400'}`}>
          {reprocessMsg}
        </div>
      )}

      {doc.filePurged && (
        <div className="mb-4 flex items-start gap-3 rounded-xl border border-amber-800/50 bg-amber-900/15 p-4">
          <FileX className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          <p className="text-[14.7px] text-amber-300/90">
            Original file removed to save space - extracted data below remains accurate.
          </p>
        </div>
      )}

      <div className={doc.filePurged ? '' : 'grid gap-6 lg:grid-cols-2 lg:items-start'}>
      <div className="min-w-0">
      <div className="mb-6 flex flex-wrap gap-2">
        {doc.uploadStatus === 'processed' && (
          <button onClick={handleSave} disabled={saveMutation.isPending} className="rounded-lg bg-emerald-700 px-4 py-2 text-[14.7px] font-medium text-white transition-colors hover:bg-emerald-600 disabled:opacity-50">
            {saveMutation.isPending ? 'Saving...' : doc.exported ? 'Save Again' : 'Save to Excel'}
          </button>
        )}
        {!doc.filePurged && (
          <>
            <button onClick={handleDownload} className="rounded-lg bg-gray-800 px-4 py-2 text-[14.7px] text-gray-300 transition-colors hover:bg-gray-700">
              Download Original
            </button>
            <button onClick={handleReprocess} disabled={reprocessing} className="rounded-lg bg-gray-800 px-4 py-2 text-[14.7px] text-gray-300 transition-colors hover:bg-gray-700 disabled:opacity-50">
              {reprocessing ? 'Reprocessing...' : 'Reprocess'}
            </button>
            <button onClick={handlePurgeFile} disabled={purgeMutation.isPending} className="rounded-lg border border-amber-800/50 bg-amber-900/20 px-4 py-2 text-[14.7px] text-amber-400 transition-colors hover:bg-amber-900/40 disabled:opacity-50">
              {purgeMutation.isPending ? 'Removing...' : 'File Delete'}
            </button>
          </>
        )}
        <button onClick={handleDelete} disabled={deleting} className="rounded-lg border border-red-800/50 bg-red-900/30 px-4 py-2 text-[14.7px] text-red-400 transition-colors hover:bg-red-900/50 disabled:opacity-50">
          {deleting ? 'Deleting...' : 'Delete'}
        </button>
      </div>

      {reprocessing && <ProcessingState message="Reprocessing with OCR and AI..." />}

      {doc.uploadStatus === 'processed' && !reprocessing && (
        <div className="space-y-3">
          <h3 className="mb-2 font-semibold text-gray-300">Extracted Fields</h3>
          {fieldsFor(doc).map((f) => {
            return (
              <div key={f.key} className={`flex items-center justify-between gap-3 rounded-xl border bg-gray-900 px-4 py-3 border-gray-800`}>
                <div className="flex min-w-0 items-center gap-2">
                  <div className="min-w-0">
                    <p className="text-[12.6px] text-gray-500">{f.label}</p>
                    <p className="truncate text-[14.7px] font-semibold text-gray-100">{f.value || 'Not available'}</p>
                  </div>
                </div>
                <button
                  onClick={() => setEditingField(f)}
                  className="shrink-0 rounded-lg border border-blue-800/50 px-3 py-1.5 text-[12.6px] font-bold text-blue-300 transition-colors hover:bg-blue-900/20"
                >
                  Edit
                </button>
              </div>
            )
          })}
          {doc.edited && (
            <p className="text-[12.6px] text-amber-400">This document has manually edited fields.</p>
          )}
        </div>
      )}
      </div>

      {!doc.filePurged && (
        <div className="min-w-0">
          {fileQuery.isError ? (
            <div className="grid h-[420px] place-items-center rounded-2xl border border-gray-800 bg-gray-900 px-4 text-center lg:h-[70vh]">
              <div>
                <p className="mb-3 text-[14.7px] text-gray-400">Could not load the original file.</p>
                <button onClick={() => fileQuery.refetch()} className="rounded-lg bg-gray-800 px-4 py-2 text-[14.7px] text-gray-300 transition-colors hover:bg-gray-700">
                  Retry
                </button>
              </div>
            </div>
          ) : viewerFile ? (
            <LazyDocumentViewer key={id} file={viewerFile} />
          ) : (
            <div className="h-[70vh] min-h-[420px] animate-pulse rounded-2xl border border-gray-800 bg-gray-900" />
          )}
        </div>
      )}
      </div>

      {editingField && (
        <CorrectionModal
          field={{ label: editingField.label, value: editingField.value, key: editingField.key }}
          onSave={handleCorrect}
          onClose={() => setEditingField(null)}
        />
      )}
    </div>
  )
}
