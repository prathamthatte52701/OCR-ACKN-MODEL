import { useState } from 'react'
import api from '../../utils/api'
import { validateUsername, validateEmail } from '../../utils/validators'
import Banner from '../../components/Banner'
import Modal from '../../components/Modal'

export default function EditUserModal({ user, onClose, onSaved }) {
  const [username, setUsername] = useState(user.username)
  const [email, setEmail] = useState(user.email)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    const err = validateUsername(username) || validateEmail(email)
    if (err) { setError(err); return }

    setSubmitting(true)
    try {
      const res = await api.patch(`/admin/users/${user.id}`, { username, email: email.trim().toLowerCase() })
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
          <label htmlFor="edit-user-email" className="ui-label mb-1 block">Email <span className="font-normal">(changing it signs the user out)</span></label>
          <input id="edit-user-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="input" />
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
