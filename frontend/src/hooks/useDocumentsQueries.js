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

// Both the initial upload pipeline and reprocess run async in a background
// task on the server - the mutation that triggers either one only confirms
// the job STARTED, not that it finished. Without this, the UI shows
// whatever status existed at that moment (still 'uploaded') and never
// checks again until the user manually refreshes. Polling every 3s while
// status is 'uploaded' (still processing) and stopping once it reaches
// 'processed'/'failed' means the page updates itself the moment the real
// result is ready, for both the initial upload and every reprocess.
function pollWhileProcessing(query) {
  const status = query.state.data?.uploadStatus
  return status === 'uploaded' ? 3000 : false
}

export function useDocument(id, options = {}) {
  return useQuery({
    queryKey: documentKeys.detail(id),
    queryFn: () => getDocument(id),
    enabled: Boolean(id),
    refetchInterval: pollWhileProcessing,
    // Default pauses the interval whenever the tab isn't focused - a user
    // who triggers reprocess/upload and switches tabs while it finishes
    // would otherwise come back to a stale "processing" screen that never
    // updates until they manually refresh, the exact bug this hook exists
    // to fix in the first place.
    refetchIntervalInBackground: true,
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
