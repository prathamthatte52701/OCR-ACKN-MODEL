import { useMutation, useQueryClient } from '@tanstack/react-query'
import { correctDocument, deleteDocument, purgeDocumentFile, reprocessDocument } from '../api/documents'
import { newExcelFile, saveDocument } from '../api/excel'
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['exports', 'history'] })
    },
  })
}

export function useNewExcelFileMutation() {
  return useMutation({
    mutationFn: (filename) => newExcelFile(filename),
  })
}
