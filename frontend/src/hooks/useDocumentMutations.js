import { useMutation, useQueryClient } from '@tanstack/react-query'
import { correctDocument, deleteDocument, purgeDocumentFile, reprocessDocument } from '../api/documents'
import { bulkSaveDocuments, newExcelFile, saveDocument } from '../api/excel'
import { documentKeys } from './useDocumentsQueries'

export function useCorrectDocument(id) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ field, value }) => correctDocument(id, field, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: documentKeys.detail(id) })
    },
  })
}

export function useReprocessDocument(id) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => reprocessDocument(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: documentKeys.detail(id) })
    },
  })
}

export function usePurgeDocumentFile(id) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => purgeDocumentFile(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: documentKeys.detail(id) })
    },
  })
}

export function useDeleteDocument(id) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => deleteDocument(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', 'list'] })
    },
  })
}

export function useSaveDocumentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (docId) => saveDocument(docId),
    // docId is the mutationFn's own argument here (this mutation is shared
    // across whichever document is saved, not scoped to one id like the
    // hooks above) - invalidate that specific document's cached detail/list
    // entries too, not just export history, so `exported` flips to true
    // immediately and a second Save shows the "Save Again" confirmation
    // without needing a manual refetch/reload first.
    onSuccess: (_message, docId) => {
      queryClient.invalidateQueries({ queryKey: ['exports', 'history'] })
      queryClient.invalidateQueries({ queryKey: documentKeys.detail(docId) })
      queryClient.invalidateQueries({ queryKey: ['documents', 'list'] })
    },
  })
}

export function useBulkSaveDocumentsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (documentIds) => bulkSaveDocuments(documentIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['exports', 'history'] })
      queryClient.invalidateQueries({ queryKey: ['documents', 'list'] })
    },
  })
}

export function useNewExcelFileMutation() {
  return useMutation({
    mutationFn: (filename) => newExcelFile(filename),
  })
}
