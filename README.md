# AckIntel AI — Acknowledgement Document Intelligence

OCR-based extraction of Number and Date from Tax Invoice / Delivery Challan
acknowledgement documents (image or PDF), with per-user auth, manual
correction, bulk upload, Excel export with yearly/monthly auto-organization,
and an admin panel with cross-user CRUD + telemetry.

Python/FastAPI rewrite of an earlier Node.js/Express app — same product,
new stack: FastAPI, MongoDB (Motor), PaddleOCR, Groq, React/Vite.

## Recent features

- **Approval decision details** - the admin can give an optional reason (max 300
  characters, plain text) when rejecting or revoking a user. A user who logs in
  with the right password sees a status card: request date while pending, or
  decision date and reason if rejected/revoked; the first login after approval
  shows the approval date. No email is sent. A wrong password never reveals any
  of this.
- **New admin panel design** - dark navy/violet theme with a left sidebar and a top bar (search, a
  bell with the real pending-approval count, account menu). The Dashboard shows gradient stat
  cards, a 30-day documents chart, a document-type donut, an OCR success gauge, a readable recent
  activity feed and one-click Approve for the oldest pending requests. Users, Approvals,
  Maintenance (real storage, server uptime and a "Danger zone" for the global delete) and every
  other admin page share the same components. Only real data is shown. Feature map:
  `docs/admin-ui-feature-map.md`.
- **Review flag for incomplete numbers** - a Tax Invoice No. that is not
  `G`/`P` + 10 digits, a Reference No. that is not 10 digits, or a Delivery
  Challan No. that is not 9 digits starting `82` (a character was dropped or
  added, or an Order number was picked up), is kept exactly as read but shown with an
  amber "Looks incomplete - please check against the original" note. Editing
  the field clears the note.
- **Document viewer** - the original file is shown beside the extracted data
  (PDF.js with zoom/pan) on the upload result, the bulk review and the detail
  page.
- **My Activity** logs uploads, OCR results, corrections, reprocessing, deletes
  and file purges, per user. The Documents page also has a month filter.
- **Admin approval for new accounts** — password signups start as `pending`
  and cannot log in (or use any route, even with an old token) until an admin
  approves them. Admins can reject, revoke or re-approve from the admin
  panel's Pending / Rejected tabs. Google sign-ups and seeded admins are
  approved automatically. Old databases: run
  `python -m app.scripts.migrate_user_status --dry-run` once, then without
  the flag, so existing users stay approved.
- **Private Export History** — a user only sees their own exports and can only
  download their own workbooks. Admins see everything through the admin
  panel, and every time an admin opens or downloads another user's data an
  audit entry is written.
- **Email is admin-only** — users can edit their name but not their email;
  an admin changes it (this signs that user out).
- **Page detection for photos** — phone photos are cropped to the paper,
  straightened and rotated upright before OCR; small camera photos are OCR'd
  without the binarizing cleanup that used to corrupt digits.
- **Stronger passwords and limits** — 8-64 characters (safe for bcrypt's
  72-byte limit), no username/email inside the
  password, max lengths on every auth field, and a request-size ceiling on
  uploads (413 before the body is read).
- **Google Sign-In** — alongside the existing email/password login, on both
  the login and signup pages. Same JWT/session contract as normal login, so
  nothing else in the app needed to change. Existing accounts with a
  matching email get linked automatically instead of creating a duplicate
  user. Google-only accounts (no password set) cannot use the
  password-reset request, since there's no password to reset.
- **Bulk-upload crash fix** — the app used to briefly hang after a restart
  because startup recovery of interrupted uploads ran before the server
  started accepting requests at all. That recovery step now runs in the
  background after the app is already serving traffic, so `/health` and
  every other route stay responsive immediately on startup.
- **Date-range filter** on the Documents page — Today / This Week / This
  Month / This Year, alongside the existing document-type and pagination
  filters.
- **View All Details** — a read-only, spreadsheet-style page
  (`/documents/view-all`) showing every saved document's extracted fields
  in one table, matching what the real Excel export contains.
- **Admin nuclear/age-based delete** — admins can permanently wipe a user's
  documents (full account or just documents older than a chosen age/year),
  gated behind a typed-confirmation-phrase + password dialog. This lives in
  the admin app only, not the main user-facing app.
- **Smarter OCR preprocessing** — before running OCR, a quick quality check
  (blur, tilt, contrast, lighting) decides whether a scan needs cleanup
  first. Good scans skip straight to OCR unchanged; only rough scans get
  the extra processing, so normal uploads aren't slowed down.

## Stack

- **Backend**: FastAPI, Motor (async MongoDB), PaddleOCR (CPU), Groq (field
  extraction via Jinja2-templated prompts), PyMuPDF (PDF handling), openpyxl
  (Excel export), PyJWT (JWT), bcrypt, slowapi (rate limiting)
- **Frontend**: React + Vite + Tailwind + TanStack Query + Zustand
- **Admin**: separate React + Vite app, same backend, role-gated
- **Database**: MongoDB Atlas
- **File storage**: GridFS (same Atlas cluster, no separate object storage)

## Project layout

```
backend/    FastAPI app (feature-based: app/features/{auth,documents,ocr,excel,admin})
frontend/   Main user-facing React app
admin/      Admin panel React app
```

## Setup

Prerequisites: Python 3.12+ (see `backend/.python-version`), Node.js 18+ and npm, a MongoDB
connection string, and (optional) Groq API keys. Everything runs locally on Windows.

### Backend

```bash
cd backend
python -m venv ../venv          # or use the existing venv/ at repo root
../venv/Scripts/activate         # Windows
pip install -r requirements-dev.txt   # exact runtime pins + ruff/black/isort/mypy/pytest
# OpenCV: keep exactly one opencv-* package (opencv-contrib-python, pinned by paddlex).
# A second one (e.g. opencv-python-headless) overwrites the same cv2/ dir; `pip list | grep opencv` must show one row.
cp .env.example .env             # fill in real values, see below
```

Required env vars (`backend/.env`):

| Var | Required | Notes |
|---|---|---|
| `MONGO_URI` | yes | MongoDB Atlas connection string |
| `JWT_SECRET` | yes | must be ≥32 chars, generate with `python -c "import secrets; print(secrets.token_hex(48))"` |
| `MONGO_DB_NAME` | no (default `docintel_transport`) | blank = default |
| `GROQ_API_KEYS` | no | comma-separated, round-robined across calls |
| `GROQ_MODEL` | no (default `openai/gpt-oss-120b`) | Groq model used for extraction. If Groq retires it, set a new one here - the app never switches models on its own; a retired model shows the user "The AI service is not set up correctly" and the cause (`MODEL_GONE`) is in `processingErrorCode` and in the server log (backend/logs/app.log) |
| `GROQ_REASONING_EFFORT` | no (unset = `low`) | `low`, `medium` or `high`. Set but blank = the parameter is not sent (use this for models without a reasoning mode). Anything else stops the app at start |
| `GROQ_MAX_TOKENS` | no (default `300`) | whole number 50-4000; blank = 300; anything else stops the app at start |
| `ENABLE_DOCS` | no (default off) | `true` exposes `/docs`, `/redoc`, `/openapi.json` (developer machines only) |
| `FRONTEND_ORIGIN` | no (default `http://localhost:5174`) | CORS allow-list; blank = default |
| `ADMIN_ORIGIN` | no (default `http://localhost:5175`) | CORS allow-list for the admin app; blank = default |
| `ADMIN_1_NAME` / `ADMIN_1_EMAIL` / `ADMIN_1_PASSWORD` and the same three for `ADMIN_2_` | only for seeding | the seed script reads the admin identities from here (none are in source); the password plaintext is used once, then only the bcrypt hash is stored |
| `GOOGLE_CLIENT_ID` | only for Google Sign-In | verifies Google ID tokens server-side; frontend needs the matching `VITE_GOOGLE_CLIENT_ID` in its own `.env`. Without it, Google Sign-In simply doesn't render — email/password login is unaffected |

After changing `GROQ_MODEL`: (1) set `GROQ_REASONING_EFFORT` blank if the new model has no reasoning mode, (2) restart the backend, (3) upload ONE test document and check it is processed.

Missing `MONGO_URI` or `JWT_SECRET` (or a `JWT_SECRET` under 32 chars) makes
the app refuse to start with a clear error — it will never silently boot
with a broken config.

### Run on the client PC

Prerequisites: the Python 3.12 venv at the repo root (`venv/`), Node.js 20.19+ or 22.12+ installed, and `backend\.env` filled in per the table above.

1. `setup.bat` - run once, and again after any frontend code change (stop the app with `stop.bat` first: running programs lock files on Windows). It installs the backend dependencies and builds both apps. Safe to run twice.
2. Seed the admin accounts once (idempotent, safe to re-run):

   ```bash
   cd backend
   ../venv/Scripts/python.exe -m app.scripts.seed_admin
   ```

3. `start.bat` - double-click it daily. It starts the backend on port 8000, the user app on 5174 and the admin app on 5175, all bound to this PC only (127.0.0.1), and opens http://localhost:5174. The admin app is http://localhost:5175. If the app is already running, it says so.
4. `stop.bat` - stops only what `start.bat` started. A document that was being processed is requeued at the next start.

Logs are in `backend\logs\app.log` (see Logs).

If a port is busy: run `stop.bat` first. If another program uses 8000, 5174 or 5175, the script names the port and does not start.

Before `git pull`: stop the app with `stop.bat`, pull, then run `setup.bat` and `start.bat`.

### Developer mode (owner only)

The client must not use developer mode. `--reload` has been seen to hang on Windows ("Reloading..." printed, the new worker never starts).

```bash
cd backend
../venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --reload
cd frontend && npm install && npm run dev   # http://localhost:5174
cd admin && npm install && npm run dev      # http://localhost:5175
```

Both dev servers proxy `/api` to the backend (see each app's `vite.config.js`).

## Logs

The server writes its log to `backend/logs/app.log` (created automatically). It rotates at 10 MB, is kept for 10 days, and old files are zipped. It can contain user emails and document details, so do not paste it into public chats.

Read the latest lines on Windows PowerShell:

```powershell
Get-Content backend\logs\app.log -Tail 100 -Wait
```

## Code quality

```bash
cd backend
../venv/Scripts/python.exe -m ruff check app
../venv/Scripts/python.exe -m black app --check
../venv/Scripts/python.exe -m isort app --check-only
../venv/Scripts/python.exe -m mypy app
```

All four are kept clean on every change.

## Tests

```bash
cd backend
../venv/Scripts/python.exe -m pytest app
```

`backend/conftest.py` forces the database name to `<name>_test` and a
test-only JWT secret before the app loads, and aborts if the DB name does not
end in `_test` — the suite never touches real data. Over 200 tests cover
the approval gate, isolation (two-user IDOR checks on every documents/excel
route), admin audit logging, passwords, field/upload limits, JWT and the
pinned requirements. Frontend and admin have no unit-test runner (`npm run
lint` and `npm run build` only).

Browser regression scripts for the PDF/image viewer live in `frontend/tests/`
(raw Playwright, all `/api/` calls mocked, no backend needed). Start `npm run dev`
and run `BASE=http://localhost:5174 node frontend/tests/test_viewer_cleanup.cjs`
or `node frontend/tests/test_viewer_break.cjs` (optional `SHOTS_DIR` for screenshots).

## Wiping data (fresh start)

`python -m app.scripts.wipe_all_except_admins --db <name>` is a dry run that only reports what would go.
Adding `--apply --i-have-a-backup` deletes ALL non-admin users, documents, GridFS files and workbook
files and keeps the admin accounts. Stop the backend first and take a `mongodump` backup before applying.

## Known limitations

- **OCR speed**: PaddleOCR on CPU takes roughly 40-90 seconds per document.
  The model stays loaded in memory (not reloaded per request), but there's
  no GPU here and Intel's oneDNN CPU acceleration is disabled — it crashes
  on this paddlepaddle version, and the one paddlepaddle version where it
  doesn't crash is independently slower on this machine (measured, not
  assumed). See `backend/app/features/ocr/paddle_runner.py` for the details.
- **Sequential processing**: uploads (single and bulk) process one at a
  time through a single global lock, by design — protects memory on a
  single-machine deployment, but means a 5-file bulk upload takes roughly
  5× one file's time, not 1×.
- **Image size**: images over 50 megapixels and PDFs with an oversized page
  are rejected (a tiny file can decode to gigabytes of RAM).
- **Password reset is admin-handled**: "Request password reset" on the login
  page sends the admin a request (email + optional note); the admin gives a
  temporary password in person or by phone, and the user must change it at
  first login. There is no emailed link.
- **Hosting**: local-only on one PC.
  Swagger/ReDoc/openapi.json are off everywhere unless `ENABLE_DOCS=true`.
- **Google linking**: an existing password account that signs in with Google
  is linked automatically (Google verified the email).
- **Admin accounts** cannot request a reset; they use
  `backend/app/scripts/reset_admin_password.py`.
- **7-day tokens**: JWTs last 7 days and are revoked only by a `tokenVersion`
  bump (password change, reject).
- **OCR accuracy on photos**: the OCR step can misread one digit on blurry or
  tilted phone photos, and on a skewed scan the invoice date can be taken from
  the neighbouring "Sales order" row. Incomplete numbers are flagged for
  review; always check a photo's values against the original.

## Security posture

Admin-approval gate on every authenticated route, JWT (PyJWT, HS256 pinned)
auth with `tokenVersion`-based session revocation, bcrypt password
hashing, NoSQL-injection-safe input validation (Pydantic-typed throughout,
no raw dict pass-through), rate limiting on auth + upload + workbook-creation
endpoints, per-user data isolation (documents/workbooks) with 404-not-403 on
cross-user access, security headers (CSP, HSTS, nosniff, frame-ancestors),
CORS restricted to explicit configured origins, admin routes gated by a
server-side role check that re-reads the DB (never trusts the JWT's role
claim) with audit logging of admin access to other users' data. See
git history for specifics.

## Admin accounts

Two admin accounts are seeded from env vars (`ADMIN_1_*`, `ADMIN_2_*` — name,
email and password). Nothing about them is hardcoded in source and only the
bcrypt hash of the password is ever persisted. Admins cannot be rejected
from the panel.
