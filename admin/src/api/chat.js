import api from '../utils/api'

export const listThreads = (signal) => api.get('/chat/threads', { signal }).then((res) => res.data)

export const getUnread = () => api.get('/chat/unread').then((res) => res.data)

export const getMessages = (params, signal) =>
  api.get('/chat/messages', { params, signal }).then((res) => res.data)

export const sendMessage = (userId, text) =>
  api.post('/chat/messages', { userId, text }).then((res) => res.data)

export const editMessage = (id, text) =>
  api.patch(`/chat/messages/${id}`, { text }).then((res) => res.data)

export const markRead = (userId, upToId) => api.post('/chat/read', { userId, upToId }).then((res) => res.data)

export const clearThread = (userId, olderThan, dryRun) =>
  api
    .post('/chat/clear', dryRun ? { userId, olderThan, dryRun: true } : { userId, olderThan, confirm: 'DELETE' })
    .then((res) => res.data)

export const clearAllChats = (password) =>
  api.post('/chat/clear-all', { password, confirm: 'DELETE' }).then((res) => res.data)
