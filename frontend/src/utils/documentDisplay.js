// Which "number" to show for a document - Tax Invoice combines its two
// number fields, Delivery Challan has just one. Was duplicated across
// DocumentCard/DocumentDetailPage/ExportHistoryPage/UploadPage in the old
// app; consolidated here during the Phase 6 port.
// "Number not read" rule - SAME truth table as backend _number_is_blank
// (backend/app/features/excel/test_number_blank_rule.py); change both together.
// Delivery Challan: blank when `number` is empty/whitespace/missing.
// Tax Invoice: blank only when BOTH taxInvoiceNo and referenceNo are empty.
// Only a processed document can show "Number not read" (not uploaded/failed).
export function isNumberBlank(doc) {
  const keys = doc.documentType === 'Tax Invoice' ? ['taxInvoiceNo', 'referenceNo'] : ['number']
  return !keys.some((k) => String(doc[k] ?? '').trim())
}

export function numberNotRead(doc) {
  return doc.uploadStatus === 'processed' && isNumberBlank(doc)
}

export function displayNumber(doc) {
  if (doc.documentType === 'Tax Invoice') {
    return [doc.taxInvoiceNo, doc.referenceNo].filter(Boolean).join(' / ') || '-'
  }
  return doc.number || '-'
}
