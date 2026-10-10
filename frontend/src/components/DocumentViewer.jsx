import { useCallback, useEffect, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const MIN_ZOOM = 50
const MAX_ZOOM = 400
const STEP = 25
const MAX_CANVAS_PIXELS = 16_000_000
const RENDER_DEBOUNCE_MS = 120

const clamp = (v) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v))

const btn =
  'inline-flex min-h-8 min-w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.045] px-2.5 text-[12.6px] font-bold text-slate-200 transition-colors hover:border-blue-300/30 hover:bg-blue-500/10 disabled:cursor-not-allowed disabled:opacity-40 pointer-coarse:min-h-10 pointer-coarse:min-w-10'

// Original-file viewer for the bulk Review Results split view. Images and PDFs share one zoom
// model: `zoom` is null (fit width) or a percent of the file's natural size, so zoom survives
// moving to the next document. PDFs are rendered one page at a time to a canvas with PDF.js
// (untrusted input: no eval, no XFA, bytes passed in as an ArrayBuffer, never a URL).
//
// Exactly one object URL and at most one PDF document live at a time; both are released when
// `file` changes and on unmount. The URL is created in a microtask that is skipped if the
// effect was already cleaned up, so StrictMode's mount/unmount/mount never leaks one.
export default function DocumentViewer({ file, index }) {
  const [objectUrl, setObjectUrl] = useState('')
  const [pdf, setPdf] = useState(null)
  const [pageNum, setPageNum] = useState(1)
  const [natural, setNatural] = useState(null) // { w, h } at 100%
  const [failed, setFailed] = useState(false)
  const [zoom, setZoom] = useState(null)
  const [boxWidth, setBoxWidth] = useState(0)
  const boxRef = useRef(null)
  const canvasRef = useRef(null)
  const zoomRef = useRef({ zoom: null, fit: 100 })

  const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
  const fitPct = natural && boxWidth ? (boxWidth / natural.w) * 100 : 100
  const pct = zoom ?? fitPct
  const scale = pct / 100
  useEffect(() => { zoomRef.current = { zoom, fit: fitPct } }, [zoom, fitPct])

  // new file: object URL, PDF document, reset page / natural size / scroll
  useEffect(() => {
    let cancelled = false
    let url = ''
    let task = null
    let doc = null
    Promise.resolve().then(async () => {
      if (cancelled) return
      url = URL.createObjectURL(file)
      setObjectUrl(url)
      setPageNum(1)
      setNatural(null)
      setFailed(false)
      setPdf(null)
      boxRef.current?.scrollTo(0, 0)
      if (!isPdf) return
      try {
        const data = new Uint8Array(await file.arrayBuffer())
        if (cancelled) return
        task = pdfjs.getDocument({
          data,
          isEvalSupported: false,
          enableXfa: false,
          disableAutoFetch: true,
          disableStream: true,
        })
        doc = await task.promise
        if (cancelled) return
        const vp = (await doc.getPage(1)).getViewport({ scale: 1 })
        if (cancelled) return
        setNatural({ w: vp.width, h: vp.height })
        setPdf(doc)
      } catch {
        if (!cancelled) setFailed(true)
      }
    })
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
      doc?.destroy()
      task?.destroy()
    }
  }, [file, isPdf])

  // container width drives fit-width (scrollbar-gutter keeps it stable when scrollbars appear)
  useEffect(() => {
    const el = boxRef.current
    const ro = new ResizeObserver(() => setBoxWidth(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // PDF page -> canvas. Old bitmap is CSS-scaled until the debounced render replaces it.
  useEffect(() => {
    if (!pdf || !boxWidth) return
    let cancelled = false
    let renderTask = null
    const timer = setTimeout(async () => {
      try {
        const page = await pdf.getPage(pageNum)
        if (cancelled) return
        const base = page.getViewport({ scale: 1 })
        let s = scale * (window.devicePixelRatio || 1)
        const px = base.width * base.height * s * s
        if (px > MAX_CANVAS_PIXELS) s *= Math.sqrt(MAX_CANVAS_PIXELS / px)
        const viewport = page.getViewport({ scale: s })
        const off = document.createElement('canvas')
        off.width = Math.floor(viewport.width)
        off.height = Math.floor(viewport.height)
        renderTask = page.render({ canvas: off, viewport })
        await renderTask.promise
        if (cancelled) return
        const canvas = canvasRef.current
        canvas.width = off.width
        canvas.height = off.height
        canvas.getContext('2d').drawImage(off, 0, 0)
        off.width = off.height = 0
        setNatural({ w: base.width, h: base.height })
      } catch (err) {
        if (!cancelled && err?.name !== 'RenderingCancelledException') setFailed(true)
      }
    }, RENDER_DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
      renderTask?.cancel()
    }
  }, [pdf, pageNum, scale, boxWidth])

  const zoomBy = useCallback((dir) => {
    const { zoom: z, fit } = zoomRef.current
    const cur = z ?? fit
    const next = dir > 0 ? Math.floor(cur / STEP) * STEP + STEP : Math.ceil(cur / STEP) * STEP - STEP
    setZoom(clamp(next))
  }, [])

  // Ctrl/Cmd+wheel zooms; non-passive so preventDefault stops the browser's page zoom
  useEffect(() => {
    const el = boxRef.current
    const onWheel = (e) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      zoomBy(e.deltaY < 0 ? 1 : -1)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomBy])

  // click-drag pan (mouse only; touch scrolls natively)
  const dragRef = useRef(null)
  const onPointerDown = (e) => {
    if (e.pointerType !== 'mouse' || e.button !== 0) return
    dragRef.current = { x: e.clientX, y: e.clientY, l: boxRef.current.scrollLeft, t: boxRef.current.scrollTop }
    boxRef.current.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e) => {
    const d = dragRef.current
    if (!d) return
    boxRef.current.scrollLeft = d.l - (e.clientX - d.x)
    boxRef.current.scrollTop = d.t - (e.clientY - d.y)
  }
  const endDrag = () => { dragRef.current = null }

  const width = natural ? natural.w * scale : undefined
  const height = natural ? natural.h * scale : undefined
  const pages = pdf?.numPages || 1

  return (
    <div
      className="min-w-0 overflow-hidden rounded-2xl border border-white/10 bg-slate-950/40"
      data-testid="review-preview"
      data-filename={file.name}
      data-index={index}
      data-object-url={objectUrl}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-white/10 px-4 py-2.5">
        <span className="min-w-0 truncate text-[13.6px] font-semibold text-slate-300" title={file.name}>{file.name}</span>
        <span className="flex shrink-0 items-center gap-3 text-[12.6px] text-slate-500">
          {(file.size / 1024).toFixed(1)} KB
          {objectUrl && (
            <a href={objectUrl} target="_blank" rel="noopener noreferrer" className="font-bold text-blue-300 no-underline hover:underline">
              Open in new tab
            </a>
          )}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-3 py-2">
        <button type="button" aria-label="Zoom out" className={btn} disabled={failed || pct <= MIN_ZOOM} onClick={() => zoomBy(-1)}>-</button>
        <span className="min-w-[3.25rem] text-center text-[12.6px] font-bold tabular-nums text-slate-300" aria-live="polite">{Math.round(pct)}%</span>
        <button type="button" aria-label="Zoom in" className={btn} disabled={failed || pct >= MAX_ZOOM} onClick={() => zoomBy(1)}>+</button>
        <button type="button" aria-label="Fit width" className={btn} disabled={failed} onClick={() => setZoom(null)}>Fit width</button>
        <button type="button" aria-label="Zoom to 100%" className={btn} disabled={failed} onClick={() => setZoom(100)}>100%</button>
        {isPdf && pages > 1 && (
          <span className="ml-auto flex items-center gap-2" role="group" aria-label="Page">
            <button type="button" aria-label="Previous page" className={btn} disabled={pageNum <= 1} onClick={() => setPageNum((p) => Math.max(1, p - 1))}>&lsaquo;</button>
            <span className="text-[12.6px] font-bold tabular-nums text-slate-300">Page {pageNum} / {pages}</span>
            <button type="button" aria-label="Next page" className={btn} disabled={pageNum >= pages} onClick={() => setPageNum((p) => Math.min(pages, p + 1))}>&rsaquo;</button>
          </span>
        )}
      </div>

      <div
        ref={boxRef}
        className="h-[70vh] min-h-[420px] cursor-grab touch-pan-x touch-pan-y select-none overflow-auto bg-slate-900 [scrollbar-gutter:stable] active:cursor-grabbing"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onDoubleClick={() => setZoom(zoom === null ? 200 : null)}
      >
        {failed ? (
          <p className="grid h-full place-items-center px-4 text-center text-[14.7px] font-semibold text-slate-400">
            Preview unavailable
          </p>
        ) : isPdf ? (
          <canvas ref={canvasRef} className="mx-auto block" style={{ width, height }} />
        ) : (
          objectUrl && (
            <img
              src={objectUrl}
              alt={`Preview of ${file.name}`}
              draggable={false}
              className={`mx-auto block max-w-none ${natural ? '' : 'opacity-0'}`}
              style={{ width, height }}
              onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
              onError={() => setFailed(true)}
            />
          )
        )}
      </div>
    </div>
  )
}
