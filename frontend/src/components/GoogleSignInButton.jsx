import { useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

// Renders the Google Identity Services button (GSI script tag lives in
// index.html) and wires its ID-token credential response to the backend's
// POST /auth/google - shared by LoginPage and SignupPage so the GSI
// init/poll logic exists exactly once. Without VITE_GOOGLE_CLIENT_ID set
// (true in this dev environment - no real Google OAuth credentials exist
// here) there's nothing to render; email/password auth is unaffected.
export default function GoogleSignInButton() {
  const { loginWithGoogle } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const containerRef = useRef(null)

  useEffect(() => {
    const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
    if (!clientId) return

    let cancelled = false
    async function handleCredential({ credential }) {
      try {
        await loginWithGoogle(credential)
        const next = searchParams.get('next')
        navigate(next && next.startsWith('/') ? next : '/', { replace: true })
      } catch {
        // No error-UI hook back into the page from here - the existing
        // email/password form's error state already covers that path.
      }
    }

    // The GSI script tag is async/defer, so `window.google` may not exist
    // yet on first render - poll briefly rather than requiring load order.
    function tryRender() {
      if (cancelled) return
      if (!window.google?.accounts?.id || !containerRef.current) {
        setTimeout(tryRender, 100)
        return
      }
      window.google.accounts.id.initialize({ client_id: clientId, callback: handleCredential })
      window.google.accounts.id.renderButton(containerRef.current, {
        theme: 'filled_black',
        size: 'large',
        width: 320,
        text: 'continue_with',
      })
    }
    tryRender()

    return () => {
      cancelled = true
    }
  }, [loginWithGoogle, navigate, searchParams])

  return <div ref={containerRef} className="flex justify-center" />
}
