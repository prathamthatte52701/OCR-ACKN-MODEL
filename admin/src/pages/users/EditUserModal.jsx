import { useState } from 'react'
import api from '../../utils/api'
import { validateUsername, validateEmail } from '../../utils/validators'
import Banner from '../../components/Banner'
import Modal from '../../components/Modal'

export default function EditUserModal({ user, onClose, onSaved }) {
  const [username, setUsername] = useState(user.username)
  const [email, setEmail] = useState(user.email)
  const googleUser = (user.authProvider || '').includes('google')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    const err = validateUsername(username) || (!googleUser && validateEmail(email))
    if (err) { setError(err); return }

    setSubmitting(true)
    try {
      // A Google user's email is read-only, so it is left out of the request.
      const payload = googleUser ? { username } : { username, email: email.trim().toLowerCase() }
      const res = await api.patch(`/admin/users/${user.id}`, payload)
      onSaved(res.data.user, 'User updated.')
    } catch (err) {
      setError(err.userMessage || 'Could not update user.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal onClose={onClose}>
      <h2 className="mb-4 text-lg font-bold text-white">Edit user</h2>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="edit-user-name" className="ui-label mb-1 block">Name</label>
          <input id="edit-user-name" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} minLength={3} maxLength={8} className="input" />
        </div>
        <div>
          <label htmlFor="edit-user-email" className="ui-label mb-1 block">Email {!googleUser && <span className="font-normal">(changing it signs the user out)</span>}</label>
          <input id="edit-user-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} readOnly={googleUser} className="input" />
          {googleUser && <p className="mt-1 text-xs text-slate-400">Signs in with Google, so the email cannot be changed.</p>}
        </div>
        <Banner error={error} />
        <div className="flex gap-3">
          <button type="submit" disabled={submitting} className="btn btn-primary">
            {submitting ? 'Saving...' : 'Save'}
          </button>
          <button type="button" onClick={onClose} className="btn btn-ghost">Cancel</button>
        </div>
      </form>
    </Modal>
  )
}
