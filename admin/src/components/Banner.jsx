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
          className={`mb-4 rounded-xl border px-3.5 py-2.5 text-[13.6px] ${error ? 'border-rose-400/25 bg-rose-500/10 text-rose-200' : 'border-emerald-400/25 bg-emerald-500/10 text-emerald-200'}`}
        >
          {error || success}
        </motion.div>
      )}
    </AnimatePresence>
  )
}
