// Pure polling decisions for the upload screens. Only the SERVER can say a file "failed"; when the
// client's own wait limit runs out the row becomes 'slow' (still processing, go check My Documents).
//
// Exports:
//   BULK_WAIT_LIMIT_MS (20 min), SINGLE_WAIT_LIMIT_MS (5 min)
//   pollDelayMs(elapsedMs)            -> 2000 for the first 2 minutes, then 5000
//   isTimedOut(elapsedMs, limitMs)    -> true once elapsed >= limit (wall clock, not attempts)
//   pollOutcome(polled)               -> 'done' | 'failed' | 'pending' (from a successful poll response)
//   SLOW_MESSAGE                      -> text shown for a 'slow' row / single upload

export const BULK_WAIT_LIMIT_MS = 20 * 60 * 1000
export const SINGLE_WAIT_LIMIT_MS = 5 * 60 * 1000
export const FAST_POLL_PHASE_MS = 2 * 60 * 1000
export const FAST_POLL_MS = 2000
export const SLOW_POLL_MS = 5000

export const SLOW_MESSAGE = 'Still processing. You can leave this page and check My Documents.'
export const UPLOAD_UNCONFIRMED_MESSAGE =
  'The upload may have gone through, but we did not get an answer. Check My Documents before uploading again.'
export const SLOW_BATCH_NOTE = 'Some files are still processing. Check My Documents before uploading them again.'

export function pollDelayMs(elapsedMs) {
  return elapsedMs < FAST_POLL_PHASE_MS ? FAST_POLL_MS : SLOW_POLL_MS
}

export function isTimedOut(elapsedMs, limitMs) {
  return elapsedMs >= limitMs
}

// A poll that answered: 'processed' -> done, 'failed' -> failed (the server decided), anything else
// ('uploaded', 'processing', a missing document...) -> keep waiting. A poll that threw (network
// error, 5xx) never reaches this function: the caller just retries on the next tick.
export function pollOutcome(polled) {
  if (polled?.uploadStatus === 'processed') return 'done'
  if (polled?.uploadStatus === 'failed') return 'failed'
  return 'pending'
}
