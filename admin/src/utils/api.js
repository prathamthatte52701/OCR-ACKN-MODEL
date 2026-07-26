import axios from 'axios'

// Separate storage key from the main app's token - the two are different
// sessions even when both apps run in the same browser.
const TOKEN_KEY = 'ackintel_admin_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

api.interceptors.request.use((config) => {
  const token = getToken()
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

function isUnreachable(err) {
  if (!err.response) return true
  return [502, 503, 504].includes(err.response.status)
}

// FastAPI's error shape: HTTPException -> { detail: "message" } (most routes)
// or { detail: { error, message, ... } } for a couple of structured cases;
// slowapi rate limits -> { error: "message" }; validation errors ->
// { detail: [{ msg, ... }, ...] }.
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

    // Session expired/invalid/no longer admin - drop the stale token and
    // bounce to admin login, skipping the auth endpoints themselves (a wrong
    // password on the admin login form is not a "session expired" event).
    const isAuthRoute = err.config?.url?.startsWith('/auth/')
    if (err.response?.status === 401 && !isAuthRoute) {
      clearToken()
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }

    return Promise.reject(err)
  }
)

export default api
