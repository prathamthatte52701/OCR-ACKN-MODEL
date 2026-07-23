import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import api from '../utils/api'
import { validateUsername, validateEmail } from '../utils/validators'
import PaginationControls from '../components/PaginationControls'
import Banner from '../components/Banner'
import Modal from '../components/Modal'
import ConfirmModal from '../components/ConfirmModal'
import { formatISTDate } from '../utils/formatDate'

const PAGE_SIZE = 30

function EditUserModal({ user, onClose, onSaved }) {
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
      <h2 className="mb-4 text-lg font-black text-white">Edit user</h2>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1 block text-[12.6px] font-semibold text-slate-400">Name</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} minLength={3} maxLength={8} className="w-full rounded-xl border border-white/10 bg-slate-950/60 px-3.5 py-2.5 text-[14.7px] text-white outline-none focus:border-emerald-300/60" />
        </div>
        <div>
          <label className="mb-1 block text-[12.6px] font-semibold text-slate-400">Email</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="w-full rounded-xl border border-white/10 bg-slate-950/60 px-3.5 py-2.5 text-[14.7px] text-white outline-none focus:border-emerald-300/60" />
        </div>
        <Banner error={error} />
        <div className="flex gap-3">
          <button type="submit" disabled={submitting} className="rounded-xl bg-gradient-to-r from-emerald-600 to-teal-500 px-4 py-2.5 text-[14.7px] font-black text-white transition-all disabled:cursor-not-allowed disabled:opacity-50">
            {submitting ? 'Saving...' : 'Save'}
          </button>
          <button type="button" onClick={onClose} className="rounded-xl border border-white/10 bg-white/[0.035] px-4 py-2.5 text-[14.7px] font-bold text-slate-300 hover:border-white/20">
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  )
}

export default function AdminUsersPage() {
  const [users, setUsers] = useState([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [totalUsers, setTotalUsers] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [editingUser, setEditingUser] = useState(null)
  const [deletingUser, setDeletingUser] = useState(null)
  const [busyId, setBusyId] = useState(null)

  async function load(pageToLoad = page) {
    setLoading(true)
    setError('')
    try {
      const res = await api.get('/admin/users', { params: { page: pageToLoad, limit: PAGE_SIZE } })
      setUsers(res.data.users || [])
      setTotalPages(res.data.totalPages || 1)
      setTotalUsers(res.data.totalUsers || 0)
    } catch (err) {
      setError(err.userMessage || 'Could not load users.')
    } finally {
      setLoading(false)
    }
  }

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { load(page) }, [page])

  async function toggleRole(user) {
    const nextRole = user.role === 'admin' ? 'user' : 'admin'
    setBusyId(user.id)
    setError('')
    setSuccess('')
    try {
      const res = await api.patch(`/admin/users/${user.id}`, { role: nextRole })
      setUsers((prev) => prev.map((u) => (u.id === user.id ? res.data.user : u)))
      setSuccess(`${user.username} is now ${nextRole}.`)
    } catch (err) {
      setError(err.userMessage || 'Could not change role.')
    } finally {
      setBusyId(null)
    }
  }

  async function deleteUser(user) {
    setBusyId(user.id)
    setError('')
    setSuccess('')
    try {
      await api.delete(`/admin/users/${user.id}`)
      setSuccess('User deleted.')
      setDeletingUser(null)
      load(page)
    } catch (err) {
      setError(err.userMessage || 'Could not delete user.')
      setDeletingUser(null)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <main className="mx-auto max-w-[1200px] px-4 py-8 sm:px-6 lg:px-10">
      <h1 className="mb-1 text-3xl font-black tracking-tight text-white">Users</h1>
      <p className="mb-6 text-[14.7px] text-slate-500">{loading ? 'Loading...' : `${totalUsers} user${totalUsers !== 1 ? 's' : ''}`}</p>

      <Banner error={error} success={success} />

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-transparent border-t-emerald-400" />
        </div>
      ) : (
        <div className="overflow-x-auto rounded-[24px] border border-emerald-300/12 bg-slate-900/60">
          <table className="w-full text-left text-[13.6px]">
            <thead>
              <tr className="border-b border-white/8 text-[11.6px] font-black uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Joined</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-white/5 last:border-0">
                  <td className="px-4 py-3 font-bold text-white">
                    <Link to={`/users/${u.id}`} className="hover:text-emerald-300 hover:underline">{u.username}</Link>
                  </td>
                  <td className="px-4 py-3 text-slate-400">{u.email}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full border px-2.5 py-1 text-[11.6px] font-black uppercase ${u.role === 'admin' ? 'border-emerald-300/25 bg-emerald-500/10 text-emerald-200' : 'border-white/10 bg-white/5 text-slate-400'}`}>
                      {u.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-500">{formatISTDate(u.createdAt)}</td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <Link to={`/users/${u.id}`} className="rounded-full border border-emerald-300/25 bg-emerald-500/10 px-3 py-1.5 text-[11.6px] font-bold text-emerald-200 hover:border-emerald-300/45">
                        View Activity
                      </Link>
                      <button disabled={busyId === u.id} onClick={() => toggleRole(u)} className="rounded-full border border-white/10 bg-white/[0.035] px-3 py-1.5 text-[11.6px] font-bold text-slate-300 hover:border-emerald-300/30 disabled:opacity-50">
                        {u.role === 'admin' ? 'Make user' : 'Make admin'}
                      </button>
                      <button onClick={() => setEditingUser(u)} className="rounded-full border border-white/10 bg-white/[0.035] px-3 py-1.5 text-[11.6px] font-bold text-slate-300 hover:border-emerald-300/30">
                        Edit
                      </button>
                      <button disabled={busyId === u.id} onClick={() => setDeletingUser(u)} className="rounded-full border border-white/10 bg-white/[0.035] px-3 py-1.5 text-[11.6px] font-bold text-rose-300 hover:border-rose-300/30 hover:bg-rose-500/10 disabled:opacity-50">
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <PaginationControls page={page} totalPages={totalPages} onChange={setPage} />

      <AnimatePresence>
        {editingUser && (
          <EditUserModal
            user={editingUser}
            onClose={() => setEditingUser(null)}
            onSaved={(updated, message) => {
              setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
              setEditingUser(null)
              setSuccess(message)
            }}
          />
        )}
        {deletingUser && (
          <ConfirmModal
            title="Delete this user?"
            message={`Delete ${deletingUser.username} (${deletingUser.email})? This permanently removes their documents, workbooks, and exports. This cannot be undone.`}
            onConfirm={() => deleteUser(deletingUser)}
            onClose={() => setDeletingUser(null)}
            busy={busyId === deletingUser.id}
            strong
          />
        )}
      </AnimatePresence>
    </main>
  )
}
