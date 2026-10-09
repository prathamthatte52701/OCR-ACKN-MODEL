import api from './client'
import { downloadBlob } from './download'
import { promptText } from '../store/dialogStore'

export function downloadWorkbook({ year, workbookId } = {}) {
  return downloadBlob('/documents/workbook/download', {
    params: workbookId ? { workbookId } : year ? { year } : {},
    fallbackFilename: 'workbook.xlsx',
  })
}

// { exports, totalExports, totalPages, currentPage } - 30 rows per page
export function exportHistory(params = {}) {
  return api.get('/documents/export-history', { params }).then((res) => res.data)
}

export function newExcelFile(filename) {
  return api.post('/documents/new-excel-file', { filename }).then((res) => res.data)
}

// Save a processed document's row to the active Excel workbook - appends
// only, no download. Two cases prompt for a workbook filename inline
// (styled Dialog, not window.prompt()) and retry once, rather than failing
// with a message that sends the user off to find "Start New Excel File"
// themselves:
//   - NEED_NEW_WORKBOOK: year rollover, the active workbook is for a past year
//   - NO_ACTIVE_WORKBOOK: this user has never exported before, so there's no
//     workbook yet at all - this is the first-export flow
export async function saveDocument(docId) {
  try {
    const res = await api.post(`/documents/${docId}/save`)
    return res.data?.message || 'Excel file appended successfully.'
  } catch (err) {
    if (err.errorCode === 'NEED_NEW_WORKBOOK' || err.errorCode === 'NO_ACTIVE_WORKBOOK') {
      const year = err.response.data.detail.year
      const filename = await promptText({
        title:
          err.errorCode === 'NO_ACTIVE_WORKBOOK'
            ? `Name your first workbook for ${year}`
            : `New workbook needed for ${year}`,
        message: err.userMessage,
        defaultValue: `Bills_${year}`,
      })
      if (!filename) return null
      await newExcelFile(filename)
      const res = await api.post(`/documents/${docId}/save`)
      return res.data?.message || 'Excel file appended successfully.'
    }
    throw err
  }
}

// Raw bulk-save call. The server answers with { succeeded, failed, blocked, notAttempted,
// dateFallback }: `blocked` is set (and the loop stopped) when there is no active workbook yet
// or the year rolled over - everything not saved is then listed in `notAttempted`.
export function bulkSaveDocuments(documentIds) {
  return api.post('/documents/bulk-save', { documentIds }).then((res) => res.data)
}

function mergeBulk(first, retry) {
  return {
    succeeded: [...(first.succeeded || []), ...(retry?.succeeded || [])],
    failed: [...(first.failed || []), ...(retry?.failed || [])],
    dateFallback: [...(first.dateFallback || []), ...(retry?.dateFallback || [])],
    blocked: retry ? retry.blocked : first.blocked,
  }
}

// "Save All" on a documents page. When the server stops with `blocked` (first export ever, or a
// new year) this asks for a workbook name once - same prompt as saveDocument() above - creates
// it and retries ONCE with only the ids that were not saved yet, so a retry can never write a
// row twice. Resolves to { succeeded, failed, dateFallback, blocked, cancelled }.
export async function saveAllDocuments(documentIds) {
  const first = await bulkSaveDocuments(documentIds)
  if (!first.blocked) return { ...mergeBulk(first), cancelled: false }

  const { error, year, message } = first.blocked
  const filename = await promptText({
    title: error === 'NO_ACTIVE_WORKBOOK' ? `Name your first workbook for ${year}` : `New workbook needed for ${year}`,
    message,
    defaultValue: `Bills_${year}`,
  })
  if (!filename) return { ...mergeBulk(first), cancelled: true }

  await newExcelFile(filename)
  const retry = await bulkSaveDocuments(first.notAttempted || [])
  return { ...mergeBulk(first, retry), cancelled: false }
}
