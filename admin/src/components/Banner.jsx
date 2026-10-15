import { AnimatePresence, motion } from 'framer-motion'

// Shared success/error feedback banner - inline, matching the main app's
// Message component convention rather than a floating toast library.
export default function Banner({ error, success }) {
  return (
    <AnimatePresence mode="wait">
      {(error || success) && (
        <motion.div
          key={error || success}
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.15 }}
          className={`mb-4 rounded-xl border px-3.5 py-2.5 text-[14px] ${error ? 'border-rose-400/45 bg-rose-400/10 text-rose-200' : 'border-teal-400/40 bg-teal-400/10 text-teal-200'}`}
        >
          {error || success}
        </motion.div>
      )}
    </AnimatePresence>
  )
}
