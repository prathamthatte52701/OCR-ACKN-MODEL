// Pure rules for the quiet auto-refresh. Plain module: no React, no browser globals at import time.
// One state object per refresher; the hook (useAutoRefresh) and the shell heartbeat are thin wrappers.
const FOCUS_BEAT_GAP_MS = 5000
const FAILURES_BEFORE_BACKOFF = 3
const BACKOFF_BEATS = 4

export function createState() {
  return { inFlight: false, lastRunAt: -Infinity, lastFocusBeatAt: -Infinity, mutation: 0, requestId: 0, failures: 0, skipBeats: 0 }
}

// Gate for one heartbeat. A beat that would otherwise run but falls in backoff uses up one skipped beat.
export function shouldRun(state, { visible, now, busy = false, modalOpen = false, minIntervalMs = 0 }) {
  if (!visible || state.inFlight || busy || modalOpen) return false
  if (now - state.lastRunAt < minIntervalMs) return false
  if (state.skipBeats > 0) {
    state.skipBeats -= 1
    return false
  }
  return true
}

// Returns what isStale needs later: the mutation version and load id this refresh started from.
export function markStarted(state, now) {
  state.inFlight = true
  state.lastRunAt = now
  return { mutation: state.mutation, requestId: state.requestId }
}

export function markFinished(state) {
  state.inFlight = false
}

// A local write (approve, delete, ...) makes any response already on its way out of date.
export function bumpMutation(state) {
  state.mutation += 1
}

// A user-triggered load (first load, filter, page) makes any refresh already on its way out of date.
export function bumpRequest(state) {
  state.requestId += 1
  return state.requestId
}

export function isStale(state, startedMutation, startedRequestId) {
  return state.mutation !== startedMutation || state.requestId !== startedRequestId
}

export function recordSuccess(state) {
  state.failures = 0
}

// 3 failures in a row, or any 429, skip the next BACKOFF_BEATS beats.
export function recordFailure(state, httpStatus) {
  state.failures += 1
  if (httpStatus === 429 || state.failures >= FAILURES_BEFORE_BACKOFF) {
    state.skipBeats = BACKOFF_BEATS
    state.failures = 0
  }
}

// The backend answered again: stop waiting out a backoff that was earned while it was down.
export function resetBackoff(state) {
  state.failures = 0
  state.skipBeats = 0
}

// Focus / tab-visible fires one immediate beat, at most once per FOCUS_BEAT_GAP_MS.
export function allowFocusBeat(state, now) {
  if (now - state.lastFocusBeatAt < FOCUS_BEAT_GAP_MS) return false
  state.lastFocusBeatAt = now
  return true
}

// Same ids in the same order with the same values for `keys` -> nothing visible changed.
export function sameRows(prev, next, keys) {
  if (prev === next) return true
  if (!Array.isArray(prev) || !Array.isArray(next) || prev.length !== next.length) return false
  return prev.every((row, i) => row.id === next[i].id && keys.every((k) => row[k] === next[i][k]))
}

export function clampPage(page, totalPages) {
  return Math.min(Math.max(1, page), Math.max(1, totalPages))
}
