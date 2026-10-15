import { Skeleton } from '../../components/ui'

// Shimmer placeholder rows for a DataTable body while its data loads.
export default function SkeletonRows({ cols, rows = 5 }) {
  return Array.from({ length: rows }, (_, r) => (
    <tr key={r} aria-hidden="true">
      {Array.from({ length: cols }, (_, c) => (
        <td key={c}><Skeleton className="h-5 w-full max-w-[160px]" /></td>
      ))}
    </tr>
  ))
}
