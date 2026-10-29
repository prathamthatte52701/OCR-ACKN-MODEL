import { useEffect } from 'react'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

// Keeps Tab inside `ref`'s element while it is mounted, starts focus on its first control and hands
// focus back to whatever had it before (the button that opened the dialog) when it unmounts.
export function useFocusTrap(ref) {
  useEffect(() => {
    const el = ref.current
    const opener = document.activeElement
    const controls = () => [...el.querySelectorAll(FOCUSABLE)]
    controls()[0]?.focus()
    function onKeyDown(e) {
      if (e.key !== 'Tab') return
      const list = controls()
      if (!list.length) return
      const first = list[0]
      const last = list[list.length - 1]
      if (!el.contains(document.activeElement) || (e.shiftKey && document.activeElement === first)) {
        e.preventDefault()
        ;(e.shiftKey ? last : first).focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      opener?.focus?.()
    }
  }, [ref])
}
