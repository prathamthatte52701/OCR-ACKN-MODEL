import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import PageBackground from '../components/PageBackground'

// Plain-language help for non-technical office staff. Every entry here
// describes a real, verified behavior of this app - nothing invented. If the
// app's actual behavior changes, this list needs to be checked again.
const TOPICS = [
  {
    q: 'I uploaded a file and got an error like "File content does not match" or "File size must be 5 MB or less"',
    a: [
      'This app only accepts PDF, JPG, JPEG, or PNG files, and each file must be smaller than 5 MB.',
      'Check what type your file is and how big it is (right-click the file → Properties on Windows, or Get Info on Mac).',
      'If it is a different file type (like Word or Excel), save/export it as a PDF first, then upload the PDF.',
      'If it is too big, ask whoever scanned it to save it at a lower quality, or take a normal photo instead of a very high-resolution scan.',
    ],
  },
  {
    q: 'I forgot to check which "Document Type" was selected before uploading',
    a: [
      'Before every upload, look at the "Document Type" buttons (Tax Invoice / Delivery Challan) above the upload box.',
      'The app always has one selected by default - if you upload without checking, it may pick the wrong one for your document.',
      'If you notice after uploading that the wrong type was used, open the document and click "Reprocess" - but first you need to fix this from the very start, so it is best to just double check the Document Type before every upload.',
      'For Bulk Upload, each file has its own dropdown next to it - check every file\'s dropdown before clicking "Upload All".',
    ],
  },
  {
    q: 'The extracted Number or Date is wrong, or empty (looks like a dash "-")',
    a: [
      'This happens when the scan or photo was blurry, dark, or the number was partly covered by a stamp.',
      'Open the document and look for a red circle icon next to the field - that means the app itself is not confident about that value and wants you to double-check it.',
      'Click "Edit" on that field and type in the correct value by looking at the original document (you can view/download the original file from the same page).',
      'If many fields look wrong, try "Reprocess" first - it re-reads the file from scratch and sometimes gets a better result.',
      'For best results next time: use good lighting, hold the camera steady, and make sure the top of the page (where the number and date are) is not covered by anything.',
    ],
  },
  {
    q: 'I clicked Save/Export and nothing seems to have happened',
    a: [
      '"Save" only works once a document has finished processing (status shows "Processed"). If it still says "Uploaded" or "Processing", wait a bit and try again.',
      'If there is no active Excel workbook yet, "Save" will tell you so - go to "My Documents" and click "Start New Excel File" first, then try saving again.',
      'If nothing downloads when you click "Export" on the Dashboard, check your browser\'s download folder or download bar - some browsers save the file quietly without a popup.',
      'If you see a red message instead of a download, read the message - it tells you exactly what went wrong.',
    ],
  },
  {
    q: 'I can\'t log in - is it a wrong password, or something else?',
    a: [
      'If the page says "Invalid email or password", either your email or password is wrong. Check for typos, and make sure Caps Lock is off.',
      'If you genuinely forgot your password, click "Forgot password?" on the login page and follow the steps there - you will need to enter your username and email correctly.',
      'If you see a message about "too many login attempts", wait about 15 minutes before trying again - this is a safety feature, not a bug.',
    ],
  },
  {
    q: 'I got suddenly logged out while using the app',
    a: [
      'Your login automatically expires after some time for security. This is normal and not an error.',
      'Simply log in again with your email and password - you will be taken back to the same page you were on.',
      'Nothing you already saved or uploaded is lost when this happens.',
    ],
  },
  {
    q: 'The page is blank, frozen, or shows "Server is currently unreachable"',
    a: [
      'This means the app cannot reach the server right now - usually a temporary internet or server issue, not something wrong with your computer.',
      'Wait about 10-30 seconds - the app checks the connection automatically and this message will disappear on its own once the server is back.',
      'If it does not go away after a few minutes, refresh the page (F5) or contact your admin/IT contact.',
    ],
  },
  {
    q: 'My document has been stuck on "Processing..." for a long time',
    a: [
      'Processing usually takes a few seconds to about a minute per document, especially if many people are uploading files at the same time - the app processes one file at a time to stay reliable.',
      'If the app tells you it is "taking longer than expected", it may still finish in the background - go check the "My Documents" page after a minute or two.',
      'If it still says "Uploaded" or "Processing" after several minutes, use the "Reprocess" button on the document\'s page to try again.',
    ],
  },
  {
    q: 'I searched for a document but it did not show up',
    a: [
      'Number search: it looks for that text anywhere inside the number, so a partial number is fine (for example, searching "7704827" will find "G0027704827").',
      'Date search: this one needs to match EXACTLY, in the format DD/MM/YYYY (for example 01/07/2026, with the leading zero and forward slashes). Typing it any other way (like 1-7-2026 or July 1) will not find it.',
      'Remember, you can only search your own documents, not documents uploaded by other people.',
      'Click "Clear Search" to see your full document list again.',
    ],
  },
  {
    q: 'I accidentally clicked Delete on a document',
    a: [
      'The app always asks "Delete this document? This cannot be undone." before actually deleting anything - if you see that popup, click Cancel and you are safe.',
      'If you already confirmed the delete, it genuinely cannot be undone by you from within the app.',
      'If this was important data, contact your admin - they may be able to help depending on how recently it happened.',
    ],
  },
  {
    q: 'I saved a document but I don\'t see it in my Excel file',
    a: [
      'Your Excel workbook has a separate sheet/tab for each month, and it is based on the DATE PRINTED ON THE DOCUMENT - not the day you clicked Save.',
      'For example, if a document is dated 15/06/2026 and you save it in July, it goes into the "June" sheet, not "July".',
      'Open the Excel file and check the sheet tabs at the bottom of the window for the month matching the document\'s own date.',
      'If a document\'s Date field itself is wrong, fix it first (Edit) - otherwise it will keep landing on the wrong month\'s sheet.',
    ],
  },
  {
    q: 'Bulk Upload won\'t let me add more files',
    a: [
      'Bulk Upload accepts a maximum of 5 files at once.',
      'If you have more than 5 documents, upload the first 5, wait for that batch to finish, then click "Start New Batch" and upload the rest.',
      'Each file in Bulk Upload still needs the right Document Type selected in its own dropdown, and still follows the same file type/size rules as a single upload.',
    ],
  },
]

function TopicItem({ topic, isOpen, onToggle }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-blue-300/12 bg-slate-900/60">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left"
        aria-expanded={isOpen}
      >
        <span className="text-[14.7px] font-bold text-white">{topic.q}</span>
        <ChevronDown className={`h-5 w-5 shrink-0 text-slate-400 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} />
      </button>
      {isOpen && (
        <div className="border-t border-white/8 px-5 py-4">
          <ul className="space-y-2.5">
            {topic.a.map((line, i) => (
              <li key={i} className="flex gap-2.5 text-[14.7px] leading-6 text-slate-300">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-400" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default function HelpPage() {
  const [openIndex, setOpenIndex] = useState(0)

  return (
    <div className="relative min-h-full overflow-hidden bg-[#020817]">
      <PageBackground variant="dots" />

      <main className="relative mx-auto max-w-[900px] px-4 py-8 sm:px-6 lg:px-10 lg:py-10">
        <div className="mb-7">
          <h1 className="text-3xl font-black tracking-[-0.03em] text-white sm:text-4xl">Help &amp; Troubleshooting</h1>
          <p className="mt-2 text-[14.7px] font-medium text-slate-500">
            Common problems and simple, step-by-step fixes. Click a question to see the answer.
          </p>
        </div>

        <div className="space-y-3">
          {TOPICS.map((topic, i) => (
            <TopicItem
              key={i}
              topic={topic}
              isOpen={openIndex === i}
              onToggle={() => setOpenIndex(openIndex === i ? -1 : i)}
            />
          ))}
        </div>

        <div className="mt-8 rounded-2xl border border-blue-300/12 bg-blue-500/[0.045] p-5 text-[14.7px] text-slate-400">
          Still stuck after trying the steps above? Contact your admin or IT contact for help.
        </div>
      </main>
    </div>
  )
}
