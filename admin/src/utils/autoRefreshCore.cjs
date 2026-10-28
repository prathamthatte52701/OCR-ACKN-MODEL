function createAutoRefreshState(opts = {}) {
  const { minVisibleFocusIntervalMs = 5000 } = opts || {}
  return { version: 0, isBusy: false, modalOpen: false, refreshInFlight: false, lastVisibleFocusAt: 0, minVisibleFocusIntervalMs }
}
function bumpVersion(state){ state.version += 1; return state.version }
function setBusy(state,busy){ state.isBusy = !!busy }
function setModalOpen(state,open){ state.modalOpen = !!open }
function shouldRefreshOnTick(state,visible){ if(!visible) return false; if(state.refreshInFlight) return false; if(state.isBusy) return false; if(state.modalOpen) return false; return true }
function shouldRefreshOnVisibleFocus(state,now){ if(now===undefined||now===null) now=Date.now(); if(state.refreshInFlight) return false; if(state.isBusy) return false; if(state.modalOpen) return false; if(state.lastVisibleFocusAt && (now - state.lastVisibleFocusAt < state.minVisibleFocusIntervalMs)) return false; state.lastVisibleFocusAt = now; return true }
function startRefresh(state){ if(state.refreshInFlight) return false; state.refreshInFlight = true; return true }
function endRefresh(state){ state.refreshInFlight = false }
function isStaleResponse(state,startedVersion){ return startedVersion < state.version }
function computeNextPageAfterShrink(currentPage,totalPages){ if(totalPages<=0) return 1; if(currentPage>totalPages) return totalPages; return currentPage }
module.exports = { createAutoRefreshState,bumpVersion,setBusy,setModalOpen,shouldRefreshOnTick,shouldRefreshOnVisibleFocus,startRefresh,endRefresh,isStaleResponse,computeNextPageAfterShrink }
