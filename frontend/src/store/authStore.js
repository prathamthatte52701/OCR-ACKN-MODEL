import { create } from 'zustand'
import { queryClient } from '../lib/queryClient'
import { removeChatKeys } from '../utils/layoutStorage'

const TOKEN_KEY = 'ackintel_token'

export const useAuthStore = create((set) => ({
  token: localStorage.getItem(TOKEN_KEY),
  user: null,
  loading: true,
  // One-time "you're approved" notice from the login response. Deliberately NOT persisted
  // anywhere (no localStorage): it lives only until the user dismisses it, and a page
  // refresh or a new login never brings it back.
  justApproved: false,
  approvedAt: null, // same lifetime as justApproved

  // `justApproved` is only touched when the caller passes it (login), so e.g. a password
  // change that re-issues the session cannot wipe a notice that is still on screen.
  setSession(token, user, justApproved, approvedAt = null) {
    localStorage.setItem(TOKEN_KEY, token)
    set({
      token,
      user,
      ...(justApproved === undefined ? {} : { justApproved, approvedAt: justApproved ? approvedAt : null }),
    })
  },
  clearJustApproved() {
    set({ justApproved: false, approvedAt: null })
  },
  setUser(user) {
    set({ user })
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY)
    queryClient.clear() // no previous user's cached data survives logout
    removeChatKeys()
    set({ token: null, user: null, justApproved: false, approvedAt: null })
  },
  setLoading(loading) {
    set({ loading })
  },
}))
