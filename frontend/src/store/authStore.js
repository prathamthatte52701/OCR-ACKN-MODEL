import { create } from 'zustand'

const TOKEN_KEY = 'ackintel_token'

export const useAuthStore = create((set) => ({
  token: localStorage.getItem(TOKEN_KEY),
  user: null,
  loading: true,

  setSession(token, user) {
    localStorage.setItem(TOKEN_KEY, token)
    set({ token, user })
  },
  setUser(user) {
    set({ user })
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY)
    set({ token: null, user: null })
  },
  setLoading(loading) {
    set({ loading })
  },
}))
