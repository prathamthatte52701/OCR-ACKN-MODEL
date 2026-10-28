export function createAutoRefreshState(opts = {}) {
  const { minVisibleFocusIntervalMs = 5000 } = opts
  return {
    version: 0,
    isBusy: false,
    modalOpen: false,
    refreshInFlight: false,
    lastVisibleFocusAt: 0,
    minVisibleFocusIntervalMs,
  }
}

export function bumpVersion(state) {
  state.version += 1
  return state.version
}

export function setBusy(state, busy) {
  state.isBusy = !!busy
}

export function setModalOpen(state, open) {
  state.modalOpen = !!open
}

export function shouldRefreshOnTick(state, visible) {
  if (!visible) return false
  if (state.refreshInFlight) return false
  if (state.isBusy) return false
  if (state.modalOpen) return false
  return true
}

export function shouldRefreshOnVisibleFocus(state, now = Date.now()) {
  if (state.refreshInFlight) return false
  if (state.isBusy) return false
  if (state.modalOpen) return false
  if (now - state.lastVisibleFocusAt < state.minVisibleFocusIntervalMs) return false
  state.lastVisibleFocusAt = now
  return true
}

export function startRefresh(state) {
  if (state.refreshInFlight) return false
  state.refreshInFlight = true
  return true
}

export function endRefresh(state) {
  state.refreshInFlight = false
}

export function isStaleResponse(state, startedVersion) {
  return startedVersion < state.version
}

export function nextPageIfMissing(listLength, page){ if(listLength===undefined||listLength===null) return page; if(listLength>0) return page; return page; }

export function computeNextPageAfterShrink(currentPage, totalPages) {
  if (totalPages <= 0) return 1
  if (currentPage > totalPages) return totalPages
  return currentPage
}
