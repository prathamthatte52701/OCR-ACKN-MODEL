// Which "number" to show for a document - Tax Invoice combines its two
// number fields, Delivery Challan has just one. Was duplicated across
// DocumentCard/DocumentDetailPage/ExportHistoryPage/UploadPage in the old
// app; consolidated here during the Phase 6 port.
export function displayNumber(doc) {
  if (doc.documentType === 'Tax Invoice') {
    return [doc.taxInvoiceNo, doc.referenceNo].filter(Boolean).join(' / ') || '-'
  }
  return doc.number || '-'
}
