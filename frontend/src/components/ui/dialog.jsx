import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { cn } from '../../lib/utils'

// eslint-disable-next-line react-refresh/only-export-components
export const Dialog = DialogPrimitive.Root
// eslint-disable-next-line react-refresh/only-export-components
export const DialogTrigger = DialogPrimitive.Trigger

export function DialogContent({ className, children, showClose = true, ...props }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" />
      <DialogPrimitive.Content
        className={cn(
          'fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-white/10 bg-gray-900 shadow-2xl outline-none',
          className
        )}
        {...props}
      >
        {children}
        {showClose && (
          <DialogPrimitive.Close className="absolute right-4 top-4 rounded-lg text-gray-500 transition-colors hover:text-gray-200">
            <X className="h-4 w-4" />
            <span className="sr-only">Close</span>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}

export function DialogHeader({ className, ...props }) {
  return <div className={cn('border-b border-gray-800 px-5 py-4', className)} {...props} />
}

export function DialogTitle({ className, ...props }) {
  return <DialogPrimitive.Title className={cn('font-semibold text-white', className)} {...props} />
}

export function DialogFooter({ className, ...props }) {
  return <div className={cn('flex justify-end gap-2 px-5 pb-5', className)} {...props} />
}
