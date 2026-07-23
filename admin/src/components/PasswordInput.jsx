import { useState, forwardRef } from 'react'

// Password <input> with a show/hide eye toggle, styled to match the existing
// text inputs across auth forms. Wraps forwardRef so callers can still keep
// native input props (autoComplete, required, minLength, ...).
const PasswordInput = forwardRef(function PasswordInput({ className = '', ...props }, ref) {
  const [visible, setVisible] = useState(false)

  return (
    <div className="relative">
      <input
        {...props}
        ref={ref}
        type={visible ? 'text' : 'password'}
        className={`w-full rounded-xl border border-white/10 bg-slate-950/60 px-3.5 py-2.5 pr-10 text-[14.7px] text-white outline-none transition-colors focus:border-emerald-300/60 ${className}`}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        tabIndex={-1}
        aria-label={visible ? 'Hide password' : 'Show password'}
        className="absolute right-1 top-1/2 -translate-y-1/2 rounded-lg p-2 text-slate-500 transition-colors hover:text-slate-200"
      >
        {visible ? (
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M3 3l18 18" />
            <path d="M10.58 10.58a2 2 0 002.83 2.83" />
            <path d="M9.88 4.24A9.77 9.77 0 0112 4c5 0 9 4 10 8-.31 1.16-.87 2.32-1.64 3.36M6.11 6.1C3.9 7.5 2.3 9.6 2 12c.66 2.47 2.24 4.61 4.35 6.02A9.77 9.77 0 0012 20c1.13 0 2.22-.18 3.24-.52" />
          </svg>
        ) : (
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        )}
      </button>
    </div>
  )
})

export default PasswordInput
