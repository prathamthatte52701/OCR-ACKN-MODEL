// The blue/cyan radial-gradient + grid-line backdrop used on every full page
// (Dashboard, Upload, Documents, ExportHistory, Help) - was hand-copy-pasted
// per page in the old app with slightly drifting gradient stops; consolidated
// into one component during the Phase 6 polish pass. `grid` toggles the
// grid-line overlay variant (Dashboard/Upload) vs the dotted overlay (My
// Documents/Export History/Help).
export default function PageBackground({ variant = 'grid' }) {
  return (
    <>
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_18%_8%,rgba(37,99,235,0.2),transparent_28%),radial-gradient(circle_at_82%_18%,rgba(6,182,212,0.16),transparent_25%),linear-gradient(180deg,rgba(15,23,42,0.18),rgba(2,6,23,0.97))]" />
      {variant === 'grid' ? (
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.035)_1px,transparent_1px)] bg-[size:56px_56px] opacity-55" />
      ) : (
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(rgba(96,165,250,0.16)_1px,transparent_1px)] bg-[size:22px_22px] opacity-25" />
      )}
    </>
  )
}
