import axios from 'axios'
import { useAuthStore } from '../store/authStore'

// Backend serializes camelCase on the wire (Phase 1 CamelModel alias_generator,
// plus raw Mongo dicts that already store camelCase keys) - the same shape the
// old Node/Express API used. Decision: keep the frontend camelCase end-to-end,
// zero request/response transform layer.

// '/api' only resolves correctly in dev, where vite.config.js proxies it to
// the local backend - that proxy doesn't exist in a static production build
// (e.g. Vercel), so a deployed build would hit its own domain instead of the
// real API. VITE_API_URL (set at deploy time) overrides it; unset locally,
// so dev keeps using the working proxy unchanged.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  timeout: 120000, // 2 min for OCR processing
})

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Server-reachability pub/sub - a network error/timeout/connection-refused
// (err.response is undefined) means the backend itself never answered, as
// opposed to a normal 4xx/5xx from a server that IS up. ServerDownBanner
// subscribes to this to show a full-page message instead of the app silently
// breaking on every failed request.
const serverDownListeners = new Set()
let serverIsDown = false
export function onServerDownChange(callback) {
  serverDownListeners.add(callback)
  callback(serverIsDown)
  return () => serverDownListeners.delete(callback)
}
function setServerDown(down) {
  if (down === serverIsDown) return
  serverIsDown = down
  serverDownListeners.forEach((cb) => cb(down))
}

// A gap between here and true unreachability: Vite's dev proxy (used for
// /api) answers with its own 502/503/504 when the backend it proxies to is
// down, rather than letting the connection failure reach axios as a
// response-less network error - the app's own routes/error handler never
// produce those statuses themselves, so treating them the same as "no
// response at all" is safe in both dev (behind the proxy) and production.
function isUnreachable(err) {
  if (!err.response) return true
  return [502, 503, 504].includes(err.response.status)
}

// FastAPI's error shape differs from the old Express API's `{ error }`:
// - HTTPException -> { detail: "message" } (most routes)
// - a few routes    -> { detail: { error, message, ... } } (e.g. workbook
//   year-rollover 409s - the frontend needs the exact code, not just prose)
// - slowapi rate limits -> { error: "message" } (its own default handler,
//   never touches `detail`)
// - 422 validation errors -> { detail: [{ msg, loc, ... }, ...] }
function extractMessage(data) {
  if (!data) return null
  if (typeof data.detail === 'string') return data.detail
  if (data.detail && typeof data.detail === 'object' && !Array.isArray(data.detail)) {
    return data.detail.message || data.detail.error || null
  }
  if (Array.isArray(data.detail) && data.detail[0]?.msg) return data.detail[0].msg
  if (typeof data.error === 'string') return data.error
  return null
}

api.interceptors.response.use(
  (res) => { setServerDown(false); return res },
  (err) => {
    setServerDown(isUnreachable(err))
    const fallback = !err.response
      ? 'Could not connect to the server. Check your internet connection and try again.'
      : 'Something went wrong. Please try again.'
    err.userMessage = extractMessage(err.response?.data) || fallback
    // The structured 409 detail (e.g. NEED_NEW_WORKBOOK) - callers that need
    // the machine-readable code read this instead of re-parsing userMessage.
    err.errorCode =
      err.response?.data?.detail && typeof err.response.data.detail === 'object'
        ? err.response.data.detail.error
        : null

    // Session expired/invalid - drop the stale token and bounce to login,
    // preserving the page the user was on so they land back there after
    // logging in again. Skip this for the auth endpoints themselves (a wrong
    // password on the login form is not a "session expired" event).
    const isAuthRoute = err.config?.url?.startsWith('/auth/')
    if (err.response?.status === 401 && !isAuthRoute) {
      useAuthStore.getState().clear()
      const next = encodeURIComponent(window.location.pathname + window.location.search)
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = `/login?next=${next}`
      }
    }

    return Promise.reject(err)
  }
)

export default api
