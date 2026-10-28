// Anything that changes the pending-approval / orphaned-file counts (Approve on any page, ...)
// dispatches this so the sidebar badges and the top-bar bell refresh at once.
export const COUNTS_CHANGED_EVENT = 'admin:counts-changed'
export const notifyCountsChanged = () => window.dispatchEvent(new Event(COUNTS_CHANGED_EVENT))

// The shell's heartbeat (AdminLayout, every 15 s while the tab is visible). Pages refresh quietly
// through useAutoRefresh on this event; they never own a timer.
export const ADMIN_TICK_EVENT = 'admin:tick'
export const notifyAdminTick = () => window.dispatchEvent(new Event(ADMIN_TICK_EVENT))
