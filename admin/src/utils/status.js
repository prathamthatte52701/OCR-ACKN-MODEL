// Badge colour for a user/document status.
export function statusTone(status) {
  return status === 'approved' || status === 'processed' ? 'green' : status === 'pending' || status === 'uploaded' ? 'amber' : status === 'rejected' || status === 'failed' ? 'red' : 'neutral'
}
