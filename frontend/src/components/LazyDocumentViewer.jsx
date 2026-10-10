import { Component, lazy, Suspense } from 'react'

// pdfjs-dist is large; load the viewer (and with it PDF.js + its worker) only when a page
// actually shows a file. Every page imports this wrapper, never DocumentViewer directly.
const DocumentViewer = lazy(() => import('./DocumentViewer'))

const DEFAULT_HEIGHT = 'h-[70vh] min-h-[420px]'
const shell = 'min-w-0 overflow-hidden rounded-2xl border border-white/10 bg-slate-950/40'

class ViewerBoundary extends Component {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error) {
    console.error('Document viewer failed:', error)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div className={`${shell} grid place-items-center gap-3 px-4 text-center ${this.props.heightClass}`}>
        <div>
          <p className="mb-3 text-[14.7px] font-semibold text-slate-400">Could not load the viewer.</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-lg border border-white/10 bg-white/[0.045] px-4 py-2 text-[12.6px] font-bold text-slate-200 hover:bg-blue-500/10"
          >
            Reload
          </button>
        </div>
      </div>
    )
  }
}

export default function LazyDocumentViewer({ heightClass = DEFAULT_HEIGHT, ...props }) {
  return (
    <ViewerBoundary heightClass={heightClass}>
      <Suspense
        fallback={
          <div className={`${shell} grid place-items-center text-[13.6px] text-slate-500 ${heightClass}`}>Loading viewer...</div>
        }
      >
        <DocumentViewer heightClass={heightClass} {...props} />
      </Suspense>
    </ViewerBoundary>
  )
}
