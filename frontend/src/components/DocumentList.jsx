import { Link } from 'react-router-dom'
import { FileText } from 'lucide-react'
import DocumentCard from './DocumentCard'

export default function DocumentList({ documents, startIndex = 0 }) {
  if (!documents || documents.length === 0) {
    return (
      <div className="rounded-[30px] border border-blue-300/12 bg-slate-900/62 p-10 text-center shadow-[0_28px_100px_rgba(2,8,23,0.35)] backdrop-blur-xl">
        <div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl border border-blue-300/18 bg-blue-500/10 text-blue-200 shadow-[0_0_42px_rgba(37,99,235,0.2)]">
          <FileText className="h-7 w-7" />
        </div>
        <h2 className="mt-5 text-2xl font-black text-white">No documents yet</h2>
        <p className="mx-auto mt-2 max-w-md text-[14.7px] leading-6 text-slate-500">
          Upload your first acknowledgement to start extracting the document number and date.
        </p>
        <Link
          to="/upload"
          className="mt-6 inline-flex rounded-2xl bg-gradient-to-r from-blue-600 to-cyan-500 px-5 py-3 text-[14.7px] font-black text-white no-underline shadow-[0_18px_45px_rgba(37,99,235,0.3)] transition-all hover:-translate-y-0.5"
        >
          Upload Document
        </Link>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
      {documents.map((doc, index) => (
        <DocumentCard key={doc._id} doc={doc} serialNumber={startIndex + index + 1} />
      ))}
    </div>
  )
}
