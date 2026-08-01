// Which confidence fields make up a document's overall card-border score -
// mirrors DocumentDetailPage.jsx's fieldsFor() field set per documentType.
const CONFIDENCE_FIELDS_BY_TYPE = {
  'Tax Invoice': ['taxInvoiceNoConfidence', 'referenceNoConfidence', 'dateConfidence'],
  'Delivery Challan': ['numberConfidence', 'dateConfidence'],
}

// Overall confidence for the card-border feature: the MINIMUM (worst) of a
// document's extracted fields, not the average - a single bad field should
// still flag the whole document for review even if its other fields are
// great, which is the point of a glance-able border. Returns null when no
// field has a confidence score at all (not yet processed, or extraction
// failed) - callers fall back to a neutral border in that case.
export function overallConfidence(doc) {
  const keys = CONFIDENCE_FIELDS_BY_TYPE[doc.documentType] || []
  const scores = keys.map((key) => doc[key]).filter((v) => v != null)
  if (scores.length === 0) return null
  return Math.min(...scores)
}

// Thresholds per spec: 90-100 green, 70-89 orange (amber), 0-69 red - reuses
// this app's existing emerald/amber/rose convention (see Dashboard.jsx's
// StatCard "green"/"amber"/"red" variants) rather than introducing new colors.
const CONFIDENCE_BORDERS = {
  green: { base: 'border-emerald-400/50', hover: 'hover:border-emerald-400/80' },
  amber: { base: 'border-amber-400/50', hover: 'hover:border-amber-400/80' },
  rose: { base: 'border-rose-400/50', hover: 'hover:border-rose-400/80' },
  neutral: { base: 'border-white/12', hover: 'hover:border-blue-300/40' },
}

export function confidenceBorder(doc) {
  const score = overallConfidence(doc)
  if (score == null) return CONFIDENCE_BORDERS.neutral
  if (score >= 90) return CONFIDENCE_BORDERS.green
  if (score >= 70) return CONFIDENCE_BORDERS.amber
  return CONFIDENCE_BORDERS.rose
}
