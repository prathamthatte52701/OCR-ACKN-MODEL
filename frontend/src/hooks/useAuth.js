import * as authApi from '../api/auth'
import { useAuthStore } from '../store/authStore'

// Thin wrapper over authStore + api/auth.js that mirrors the old app's
// useAuth() hook shape, so pages ported from the old AuthContext barely
// change.
export function useAuth() {
  const user = useAuthStore((s) => s.user)
  const loading = useAuthStore((s) => s.loading)
  const setSession = useAuthStore((s) => s.setSession)
  const setUser = useAuthStore((s) => s.setUser)
  const clear = useAuthStore((s) => s.clear)

  async function login(email, password) {
    const data = await authApi.login(email, password)
    setSession(data.token, data.user)
    return data.user
  }

  async function loginWithGoogle(idToken) {
    const data = await authApi.loginWithGoogle(idToken)
    setSession(data.token, data.user)
    return data.user
  }

  async function signup(username, email, password) {
    const data = await authApi.signup(username, email, password)
    return data.message
  }

  function logout() {
    clear()
  }

  async function updateProfile(fields) {
    const user = await authApi.updateProfile(fields)
    setUser(user)
    return user
  }

  async function changePassword(currentPassword, newPassword, confirmNewPassword) {
    const data = await authApi.changePassword(currentPassword, newPassword, confirmNewPassword)
    setSession(data.token, data.user)
    return data.user
  }

  return { user, loading, login, loginWithGoogle, signup, logout, updateProfile, changePassword }
}
