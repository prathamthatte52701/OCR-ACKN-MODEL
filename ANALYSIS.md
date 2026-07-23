# Pivot Analysis — Node/Express/React → Python/FastAPI/React

Source read directly: `E:\OCR ACKN MODEL\OCR main codebase\OCR project AJ` (backend/frontend/admin, all routes/models/middleware/services, README.md).

**Note:** `PRE_PIVOT_BASELINE.md` referenced in the master prompt does not exist anywhere in the old repo (checked recursively, including node_modules false-positives on "baseline-browser-mapping"). Proceeding without it — flagging as open question below. OCR accuracy regression will need fresh baseline captured from current app behavior instead.

## 1. Feature/Route/Model Inventory

### Auth (`routes/auth.js`, `middleware/auth.js`, `middleware/isAdmin.js`, `utils/validators.js`)
- `POST /api/auth/signup` — rate limited (15/hr/IP), validates email/username/password types+format, generic duplicate-email error (timing-safe: hash happens before uniqueness check), no auto-login.
- `POST /api/auth/login` — dual rate limit (per-email 20/15min, per-IP 100/15min), rejects non-string email/password before DB query (NoSQL injection guard), JWT `{userId, tokenVersion, role}`, 7d TTL.
- `GET /api/auth/me`, `PATCH /api/auth/me` — profile read/update, duplicate-email guard on update too.
- `POST /api/auth/change-password` — verify current, bump `tokenVersion`, re-issue token so current tab stays logged in.
- `POST /api/auth/forgot-password/verify`, `POST /api/auth/forgot-password/reset` — username+email match (no OTP/email step), generic mismatch error, re-verifies pair on reset (doesn't trust verify step), bumps `tokenVersion`.
- `requireAuth` middleware — verifies JWT, re-reads `tokenVersion` from DB, rejects if mismatched (session revocation).
- `isAdmin` middleware — re-reads role from DB (never trusts JWT claim), runs after `requireAuth`.
- Password rule: 8-32 chars, upper+lower+digit+special, no whitespace.
- Username rule: 3-8 chars trimmed.
- Admin seed (`scripts/seedAdmin.js`): Arjav Jain (arjav99jain@gmail.com) / Pratham Thatte (prathamthatte527@gmail.com), idempotent.

### Documents (`routes/documents.js`, gated by `requireAuth` at mount)
- `POST /upload` (single), `POST /bulk-upload` (max 5, sequential) — multipart, stored in GridFS.
- `GET /` — list, paginated, search, grouped by documentType.
- `GET /:id`, `GET /:id/download`.
- `POST /:id/reprocess`.
- `DELETE /:id` — soft delete (`isDeleted`/`deletedAt`).
- `PATCH /:id/correct` — manual correction, logs to `Correction` model, marks `edited: true`.
- `GET /workbooks`, `GET /workbook/download`, `POST /new-excel-file` — workbook management, yearly rollover.
- `GET /export-history` — **intentionally NOT scoped to userId** (global visibility — preserve exactly).
- `POST /:id/save` — export to Excel, writes `ExportedRow`.
- `recoverInterruptedUploads()` — called on server boot to requeue anything stuck mid-processing after a crash/restart.

### Admin (`routes/admin.js`, gated by `requireAuth` + `isAdmin` at mount)
- `/users` CRUD (get list, get one, patch, delete), `/documents` CRUD, `/workbooks` (list + download), `/exports`, `/logs`, `/telemetry`.

### OCR/Extraction pipeline (`services/ocr.js`, `services/ocr-worker.js`, `services/pdf-render-worker.js`, `services/groq.js`)
- Tesseract.js OCR in a worker thread; PDF pages rendered to images in a separate worker before OCR.
- Groq call for structured field extraction from OCR text, per documentType-specific prompt.
- Hardcoded safety-net validation: Tax Invoice number must start with `G` — enforced in code, never trusted from the AI output alone.
- Per-field confidence values (0-100) derived from AI-side signal, not Tesseract (Tesseract gives no per-field score).

### Excel (`services/excel.js`)
- exceljs-based, yearly workbook / monthly sheet auto-organization, per-user file namespacing on disk in `backend/exports/`.
- `Settings` model tracks each user's currently-active workbook name + year (rollover detection on every save).

### Security posture already hardened (must be preserved 1:1)
- Per-user isolation on documents/workbooks (query always includes `userId`), **except** `ExportedRow`/export-history which is global by design.
- NoSQL injection guard: explicit `typeof x === 'string'` checks before any Mongo query touches user input.
- Rate limiting: signup 15/hr/IP, login 20/15min/email + 100/15min/IP, forgot-password 20/15min.
- Session revocation via `tokenVersion` bump on password change (both change-password and forgot-password paths).
- `isAdmin` always re-reads DB role, never trusts JWT claim.
- helmet with `crossOriginResourcePolicy: false` (only relaxation, needed for cross-origin JSON/blob fetches in dev).
- Malformed ObjectId handling via `utils/objectId.js` (`isValidObjectId`).
- Global uncaught-exception/unhandled-rejection handlers keep the process alive instead of crashing.
- Mongo connect-with-retry (5 attempts, 3s backoff) + custom DNS resolvers (8.8.8.8/1.1.1.1) to work around this machine's SRV lookup flakiness.

### Frontend/Admin apps
- React+Vite, pages match routes 1:1 (Dashboard, DocumentsPage, DocumentDetailPage, ExportHistoryPage, Upload, Login/Signup/ForgotPassword, Profile, Help, NotFound). Admin app mirrors with its own Login/ForgotPassword/Users/Documents/Workbooks/Logs/Profile pages.
- Confirm-delete modals (`ConfirmModal.jsx` in both apps), `ServerDownBanner.jsx`, `PasswordInput.jsx` (both apps) — reusable components to port as-is.
- **Chat feature confirmed absent** — no chat routes, models, or components found anywhere in the repo. Nothing to avoid rebuilding beyond not inventing one.

## 2. Node → Python Stack Mapping

| Old | New |
|---|---|
| Express routes | FastAPI routers, one per feature folder |
| Mongoose schemas | Pydantic models (`app/features/*/models.py`) |
| `middleware/auth.js` (`requireAuth`) | FastAPI dependency `get_current_user` |
| `middleware/isAdmin.js` | FastAPI dependency `require_admin` (depends on `get_current_user`) |
| `utils/validators.js` | `app/core/validators.py` (same regexes, ported 1:1) |
| `jsonwebtoken` | `python-jose` |
| `bcryptjs` | `passlib[bcrypt]` / `bcrypt` |
| `express-rate-limit` | `slowapi` |
| `helmet` | custom `SecurityHeadersMiddleware` in `app/core/` |
| Tesseract.js + worker threads | PaddleOCR (CPU) — no worker-thread equivalent needed, run via `asyncio.to_thread`/process pool since PaddleOCR is sync/blocking |
| `pdf-render-worker.js` | PyMuPDF (`fitz`) page-to-image rendering |
| `services/groq.js` | `app/features/ocr/providers/groq_provider.py` behind an `AIProvider` interface (so OpenAI/Claude/Gemini can be swapped via config) |
| Hardcoded prompt strings | Jinja2 templates in `app/features/ocr/prompts/` |
| GridFS (Node driver) | GridFS via Motor (`AsyncIOMotorGridFSBucket`) |
| exceljs | openpyxl |
| `utils/objectId.js` | Custom Pydantic `PyObjectId` annotated type |
| `scripts/seedAdmin.js` | `app/scripts/seed_admin.py` |
| `console.log`/`console.error` | Loguru |

## 3. Phase Breakdown (proposed ordering, with reasoning)

1. **Project skeleton + config + DB models** (this session, Phase 1) — nothing else can be tested without a running app + DB connection.
2. **Auth + security** (this session, Phase 2) — every other feature is gated behind auth; building documents/OCR before auth would mean re-testing auth integration later anyway.
3. **OCR + extraction pipeline** (incl. "G" prefix safety net) — the core value of the app; needs auth done so uploads can be user-scoped from day one.
4. **Excel export system** — depends on documents/OCR existing to have real data to export.
5. **Admin panel backend** — depends on documents/users/workbooks all existing since it's a CRUD/analytics layer over them.
6. **Frontend reconnection + polish** — last, since API shapes need to be stable first; reduces rework.
7. **Full regression + accuracy testing** — final gate before calling the pivot done.

This matches the master prompt's own ordering — no deviation proposed, it's already dependency-correct.

## 4. Open Questions

1. `PRE_PIVOT_BASELINE.md` does not exist in the old repo. Do you have it elsewhere, or should Phase 3 generate a fresh baseline by running the *old* app against the same test documents before touching OCR in the new stack?
2. camelCase → snake_case: old API responses are camelCase (`taxInvoiceNo`, `uploadStatus`, etc). New Pydantic models will be snake_case internally but I'll alias to camelCase on the wire (`Field(alias=...)` + `populate_by_name`) so the frontend needs **zero changes** to field names when reconnected in Phase 6. Confirm this is preferred over changing the frontend to snake_case.
3. GridFS vs Cloudinary/S3: keeping GridFS — no strong reason to move off it. It's already Mongo Atlas-backed (same cluster, no new service/credentials), file sizes here are small scanned docs/PDFs (not video/large media where GridFS starts to hurt), and Motor's `AsyncIOMotorGridFSBucket` is a direct async equivalent of the old driver's GridFS usage. Moving to S3/Cloudinary would add a new vendor/credential surface for no functional gain at this scale.
4. Old repo's rate limits found in code (for the record, since master prompt guessed "3x" without giving exact numbers): signup 15/hr/IP, login 20/15min/email + 100/15min/IP, forgot-password 20/15min. Phase 2 below replicates these exact numbers.

Proceeding directly into Phase 1 + Phase 2 per your instruction not to stop.
