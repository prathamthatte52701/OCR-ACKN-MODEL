// pathname per history index for this tab, so BackButton can tell where "back" lands
// without leaving the app. Unknown (e.g. after a reload) just means "no information".
const stack = {}

export function recordLocation(pathname) {
  const idx = window.history.state?.idx
  if (typeof idx === 'number') stack[idx] = pathname
}

export function previousPath() {
  const idx = window.history.state?.idx
  return typeof idx === 'number' ? stack[idx - 1] : undefined
}
