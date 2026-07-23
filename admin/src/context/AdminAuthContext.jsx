import { createContext, useContext, useEffect, useState } from 'react'
import api, { getToken, setToken, clearToken } from '../utils/api'

const AdminAuthContext = createContext(null)

const NOT_ADMIN_MESSAGE = 'This account does not have admin access.'

export function AdminAuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const token = getToken()
    if (!token) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- no session to restore
      setLoading(false)
      return
    }
    api.get('/auth/me')
      .then((res) => {
        if (cancelled) return
        // A previously-admin token whose role has since been revoked (or a
        // token that never belonged to an admin) must not resume a session -
        // this is the app-level gate; the real enforcement is server-side
        // require_admin on every actual admin route.
        if (res.data.user?.role !== 'admin') {
          clearToken()
          setUser(null)
          return
        }
        setUser(res.data.user)
      })
      .catch(() => { if (!cancelled) clearToken() })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  // Reuses the SAME backend login route the main app uses - the backend does
  // not gate login by role. Any account can authenticate here; this app just
  // refuses to store the session or proceed unless role === 'admin'.
  async function login(email, password) {
    const res = await api.post('/auth/login', { email, password })
    if (res.data.user?.role !== 'admin') {
      throw Object.assign(new Error(NOT_ADMIN_MESSAGE), { userMessage: NOT_ADMIN_MESSAGE })
    }
    setToken(res.data.token)
    setUser(res.data.user)
    return res.data.user
  }

  function logout() {
    clearToken()
    setUser(null)
  }

  async function changePassword(currentPassword, newPassword, confirmNewPassword) {
    const res = await api.post('/auth/change-password', { currentPassword, newPassword, confirmNewPassword })
    if (res.data.user?.role !== 'admin') {
      clearToken()
      setUser(null)
      throw Object.assign(new Error(NOT_ADMIN_MESSAGE), { userMessage: NOT_ADMIN_MESSAGE })
    }
    setToken(res.data.token)
    setUser(res.data.user)
    return res.data.user
  }

  return (
    <AdminAuthContext.Provider value={{ user, loading, login, logout, changePassword }}>
      {children}
    </AdminAuthContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAdminAuth() {
  const ctx = useContext(AdminAuthContext)
  if (!ctx) throw new Error('useAdminAuth must be used within AdminAuthProvider')
  return ctx
}
