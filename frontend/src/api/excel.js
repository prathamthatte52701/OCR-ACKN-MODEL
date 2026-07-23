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
// only, no download. On a year rollover the backend responds 409 with a
// structured { error: 'NEED_NEW_WORKBOOK', year, message } detail; this
// prompts for the new workbook's name (styled Dialog, not window.prompt())
// and retries once. If there's no active workbook at all yet, the backend
// only gives a plain message (no structured code to auto-prompt from) - the
// caller shows that as-is and points the user at "Start New Excel File".
export async function saveDocument(docId) {
  try {
    const res = await api.post(`/documents/${docId}/save`)
    return res.data?.message || 'Excel file appended successfully.'
  } catch (err) {
    if (err.errorCode === 'NEED_NEW_WORKBOOK') {
      const filename = await promptText({
        title: `New workbook needed for ${err.response.data.detail.year}`,
        message: err.userMessage,
        defaultValue: `Bills_${err.response.data.detail.year}`,
      })
      if (!filename) return null
      await newExcelFile(filename)
      const res = await api.post(`/documents/${docId}/save`)
      return res.data?.message || 'Excel file appended successfully.'
    }
    throw err
  }
}
