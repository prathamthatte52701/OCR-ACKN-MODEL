import api from './client'
import { downloadBlob } from './download'

export function listDocuments(params) {
  return api.get('/documents', { params }).then((res) => res.data)
}

export function getDocument(id) {
  return api.get(`/documents/${id}`).then((res) => res.data.document)
}

export function uploadDocument(file, documentType) {
  const formData = new FormData()
  formData.append('document', file)
  formData.append('documentType', documentType)
  return api
    .post('/documents/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    .then((res) => res.data.document)
}

export function bulkUploadDocuments(files, documentTypes) {
  const formData = new FormData()
  files.forEach((file) => formData.append('documents', file))
  documentTypes.forEach((type) => formData.append('documentTypes', type))
  return api
    .post('/documents/bulk-upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    .then((res) => res.data.results)
}

export function correctDocument(id, field, value) {
  return api.patch(`/documents/${id}/correct`, { field, value }).then((res) => res.data.document)
}

export function reprocessDocument(id) {
  return api.post(`/documents/${id}/reprocess`).then((res) => res.data)
}

export function deleteDocument(id) {
  return api.delete(`/documents/${id}`).then((res) => res.data)
}

// Permanently removes the stored original file (GridFS) while leaving the
// document's extracted metadata untouched - distinct from deleteDocument()
// (soft-delete of the whole record). Irreversible.
export function purgeDocumentFile(id) {
  return api.post(`/documents/${id}/purge-file`).then((res) => res.data)
}

export function downloadDocument(id, fallbackFilename) {
  return downloadBlob(`/documents/${id}/download`, { fallbackFilename })
}

export function trainingStats() {
  return api.get('/documents/training-stats').then((res) => res.data)
}
