import api from '../utils/api'

export const listThreads = (signal) => api.get('/chat/threads', { signal }).then((res) => res.data)

export const getUnread = () => api.get('/chat/unread').then((res) => res.data)

export const getMessages = (params, signal) =>
  api.get('/chat/messages', { params, signal }).then((res) => res.data)

export const sendMessage = (userId, text) =>
  api.post('/chat/messages', { userId, text }).then((res) => res.data)

// One file per message; `text` is an optional caption. onProgress gets 0-100.
export const sendChatFile = (userId, file, text, onProgress) => {
  const form = new FormData()
  form.append('userId', userId)
  if (text) form.append('text', text)
  form.append('file', file)
  return api
    .post('/chat/messages/file', form, {
      onUploadProgress: (e) => e.total && onProgress?.(Math.round((e.loaded / e.total) * 100)),
    })
    .then((res) => res.data)
}

// The bytes as a Blob (a plain <img src> cannot send the auth header).
export const fetchChatFile = (id) => api.get(`/chat/files/${id}`, { responseType: 'blob' }).then((res) => res.data)

export const editMessage = (id, text) =>
  api.patch(`/chat/messages/${id}`, { text }).then((res) => res.data)

export const markRead = (userId, upToId) => api.post('/chat/read', { userId, upToId }).then((res) => res.data)

export const clearThread = (userId, olderThan, dryRun) =>
  api
    .post('/chat/clear', dryRun ? { userId, olderThan, dryRun: true } : { userId, olderThan, confirm: 'DELETE' })
    .then((res) => res.data)

export const clearAllChats = (password) =>
  api.post('/chat/clear-all', { password, confirm: 'DELETE' }).then((res) => res.data)
