import { motion } from 'framer-motion'

// Shared backdrop-fade + scale-in wrapper for the Edit User / Edit Document
// modals. Always mount this INSIDE an <AnimatePresence> in the parent so the
// exit animation runs on close.
export default function Modal({ onClose, children, maxWidth = 'max-w-sm' }) {
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
