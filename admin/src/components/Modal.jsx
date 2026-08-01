import { useEffect } from 'react'
import { motion } from 'framer-motion'

// Shared backdrop-fade + scale-in wrapper for the Edit User / Edit Document
// modals. Always mount this INSIDE an <AnimatePresence> in the parent so the
// exit animation runs on close.
//
// Esc-to-close lives here (one listener, inherited by every admin modal:
// ConfirmModal, ConfirmPurgeModal, EditUserModal, EditDocumentModal) rather
// than in each modal - this component only ever calls `onClose`, never a
// confirm/submit action, so it's safe to share unconditionally: for
// ConfirmPurgeModal (the nuke flow) `onClose` is that modal's own
// `handleClose`, which already no-ops while a delete is in flight, and
// Enter-to-confirm is deliberately NOT wired here or anywhere nuke-related -
// see ConfirmPurgeModal.jsx.
export default function Modal({ onClose, children, maxWidth = 'max-w-sm' }) {
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
      onClick={onClose}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
    >
      <motion.div
        className={`w-full ${maxWidth} rounded-[24px] border border-emerald-300/18 bg-slate-900/95 p-6 shadow-2xl`}
        onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, scale: 0.96, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 8 }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
      >
        {children}
      </motion.div>
    </motion.div>
  )
}
