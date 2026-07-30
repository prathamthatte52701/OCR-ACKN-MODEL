import api from './client'

export function login(email, password) {
  return api.post('/auth/login', { email, password }).then((res) => res.data)
}

export function loginWithGoogle(idToken) {
  return api.post('/auth/google', { idToken }).then((res) => res.data)
}

export function signup(username, email, password) {
  return api.post('/auth/signup', { username, email, password }).then((res) => res.data)
}

export function fetchMe() {
  return api.get('/auth/me').then((res) => res.data.user)
}

export function updateProfile(fields) {
  return api.patch('/auth/me', fields).then((res) => res.data.user)
}

export function changePassword(currentPassword, newPassword, confirmNewPassword) {
  return api
    .post('/auth/change-password', { currentPassword, newPassword, confirmNewPassword })
    .then((res) => res.data)
}

export function forgotPasswordVerify(username, email) {
  return api.post('/auth/forgot-password/verify', { username, email }).then((res) => res.data)
}

export function forgotPasswordReset(username, email, newPassword, confirmNewPassword) {
  return api
    .post('/auth/forgot-password/reset', { username, email, newPassword, confirmNewPassword })
    .then((res) => res.data)
}
