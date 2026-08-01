import api from './client'

// Shared by downloadWorkbook(), downloadDocument(), and downloadAllDocuments()
// - all need the Authorization header attached (so this goes through the
// shared `api` instance, not a raw window.open()/<a href> navigation, which
// sends no auth header and would 401 against this backend's uniformly-
// enforced Bearer auth), blob-response handling, and Content-Disposition
// filename parsing. Blob responses also hide JSON error bodies from the
// normal response interceptor, so failures are re-parsed from the blob text
// here. Returns the response so callers that need more than the download
// itself (e.g. Download All's X-Download-Included/Skipped/Total headers)
// can read it - existing callers just ignore the return value.
export async function downloadBlob(url, { params, data, method = 'get', fallbackFilename } = {}) {
  let res
  try {
    res = await api.request({ url, method, params, data, responseType: 'blob' })
  } catch (err) {
    let body
    if (err.response?.data instanceof Blob) {
      try {
        body = JSON.parse(await err.response.data.text())
      } catch {
        body = null
      }
    } else {
      body = err.response?.data || null
    }
    const message =
      (typeof body?.detail === 'string' && body.detail) ||
      body?.detail?.message ||
      body?.error ||
      err.userMessage
    throw Object.assign(err, { userMessage: message })
  }

  const disposition = res.headers?.['content-disposition'] || ''
  const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i)
  const filename = match ? decodeURIComponent(match[1]) : fallbackFilename

  const blobUrl = window.URL.createObjectURL(new Blob([res.data]))
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = filename
  // Must be attached to the DOM for the browser to reliably honor the
  // click-triggered download (a detached anchor's click() is inconsistent
  // across browsers, headless Chromium included). Revoke is deferred since
  // revoking synchronously can race the browser's own download handoff.
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => window.URL.revokeObjectURL(blobUrl), 1000)
  return res
}
