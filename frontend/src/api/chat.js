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
