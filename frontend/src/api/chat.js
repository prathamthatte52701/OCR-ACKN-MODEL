import api from './client'

export const listChatAdmins = () => api.get('/chat/admins').then((res) => res.data)

export const getChatMessages = (params) => api.get('/chat/messages', { params }).then((res) => res.data)

export const sendChatMessage = (toAdminId, text) =>
  api.post('/chat/messages', { toAdminId, text }).then((res) => res.data)

export const editChatMessage = (id, text) =>
  api.patch(`/chat/messages/${id}`, { text }).then((res) => res.data)

export const markChatRead = (upToId) => api.post('/chat/read', { upToId }).then((res) => res.data)

export const getChatUnread = () => api.get('/chat/unread').then((res) => res.data)

export const getChatSettings = () => api.get('/chat/settings').then((res) => res.data)

export const putChatColor = (color) => api.put('/chat/settings/color', { color }).then((res) => res.data)

// One file per message; `text` is an optional caption. onProgress gets 0-100.
export const sendChatFile = (toAdminId, file, text, onProgress) => {
  const form = new FormData()
  form.append('toAdminId', toAdminId)
  if (text) form.append('text', text)
  form.append('file', file)
  return api
    .post('/chat/messages/file', form, {
      onUploadProgress: (e) => e.total && onProgress?.(Math.round((e.loaded / e.total) * 100)),
    })
    .then((res) => res.data)
}

// The bytes as a Blob. Done with axios (not <img src>) because the request needs the auth header.
export const fetchChatFile = (id) => api.get(`/chat/files/${id}`, { responseType: 'blob' }).then((res) => res.data)
