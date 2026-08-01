import api from './client'
import { downloadBlob } from './download'
import { promptText } from '../store/dialogStore'

export function listWorkbooks() {
  return api.get('/documents/workbooks').then((res) => res.data)
}

export function downloadWorkbook({ year, workbookId } = {}) {
  return downloadBlob('/documents/workbook/download', {
    params: workbookId ? { workbookId } : year ? { year } : {},
    fallbackFilename: 'workbook.xlsx',
  })
}

export function exportHistory() {
  return api.get('/documents/export-history').then((res) => res.data.exports)
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

// "Save All" on a documents page - saves every document id currently
// rendered on that page (already-exported ones included, same as an
// individual "Save Again"). No NEED_NEW_WORKBOOK/NO_ACTIVE_WORKBOOK
// auto-retry like saveDocument() above - if there's no active workbook yet,
// every entry in the batch just comes back failed with that reason; the
// user resolves it once via a single Save or "Start New Excel File", same
// as today, then Save All works.
export function bulkSaveDocuments(documentIds) {
  return api.post('/documents/bulk-save', { documentIds }).then((res) => res.data)
}
