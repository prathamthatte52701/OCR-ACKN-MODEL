// Anything that changes the pending-approval / orphaned-file counts (Approve on any page, ...)
// dispatches this so the sidebar badges and the top-bar bell refresh at once.
export const COUNTS_CHANGED_EVENT = 'admin:counts-changed'
export const notifyCountsChanged = () => window.dispatchEvent(new Event(COUNTS_CHANGED_EVENT))
