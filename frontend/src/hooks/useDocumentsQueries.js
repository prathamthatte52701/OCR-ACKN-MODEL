import { useQuery } from '@tanstack/react-query'
import { getDocument, listDocuments, trainingStats } from '../api/documents'
import { exportHistory } from '../api/excel'

export const documentKeys = {
  list: (params) => ['documents', 'list', params],
  detail: (id) => ['documents', 'detail', id],
  trainingStats: ['documents', 'training-stats'],
}

export function useDocumentsList(params, options = {}) {
  return useQuery({
    queryKey: documentKeys.list(params),
    queryFn: () => listDocuments(params),
    ...options,
  })
}

export function useDocument(id, options = {}) {
  return useQuery({
    queryKey: documentKeys.detail(id),
    queryFn: () => getDocument(id),
    enabled: Boolean(id),
    ...options,
  })
}

export function useTrainingStats() {
  return useQuery({
    queryKey: documentKeys.trainingStats,
    queryFn: trainingStats,
  })
}

export function useExportHistory() {
  return useQuery({
    queryKey: ['exports', 'history'],
    queryFn: exportHistory,
  })
}
