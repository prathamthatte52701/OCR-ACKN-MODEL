import { useState, forwardRef } from 'react'
import { Eye, EyeOff } from 'lucide-react'

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
        className={`w-full rounded-xl border border-white/10 bg-slate-950/60 px-3.5 py-2.5 pr-10 text-[14.7px] text-white outline-none transition-colors focus:border-blue-300/60 ${className}`}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        tabIndex={-1}
        aria-label={visible ? 'Hide password' : 'Show password'}
        className="absolute right-1 top-1/2 -translate-y-1/2 rounded-lg p-2 text-slate-500 transition-colors hover:text-slate-200"
      >
        {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  )
})

export default PasswordInput
