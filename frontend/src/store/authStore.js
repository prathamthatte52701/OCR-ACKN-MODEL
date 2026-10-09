import { create } from 'zustand'

const TOKEN_KEY = 'ackintel_token'

export const useAuthStore = create((set) => ({
  token: localStorage.getItem(TOKEN_KEY),
  user: null,
  loading: true,
  // One-time "you're approved" notice from the login response. Deliberately NOT persisted
  // anywhere (no localStorage): it lives only until the user dismisses it, and a page
  // refresh or a new login never brings it back.
  justApproved: false,

  // `justApproved` is only touched when the caller passes it (login), so e.g. a password
  // change that re-issues the session cannot wipe a notice that is still on screen.
  setSession(token, user, justApproved) {
    localStorage.setItem(TOKEN_KEY, token)
    set({ token, user, ...(justApproved === undefined ? {} : { justApproved }) })
  },
  clearJustApproved() {
    set({ justApproved: false })
  },
  setUser(user) {
    set({ user })
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY)
    set({ token: null, user: null, justApproved: false })
  },
  setLoading(loading) {
    set({ loading })
  },
}))
