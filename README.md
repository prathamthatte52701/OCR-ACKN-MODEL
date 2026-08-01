# AckIntel AI — Acknowledgement Document Intelligence

OCR-based extraction of Number and Date from Tax Invoice / Delivery Challan
acknowledgement documents (image or PDF), with per-user auth, manual
correction, bulk upload, Excel export with yearly/monthly auto-organization,
and an admin panel with cross-user CRUD + telemetry.

Python/FastAPI rewrite of an earlier Node.js/Express app — same product,
new stack: FastAPI, MongoDB (Motor), PaddleOCR, Groq, React/Vite.

## Recent features

- **Google Sign-In** — alongside the existing email/password login, on both
  the login and signup pages. Same JWT/session contract as normal login, so
  nothing else in the app needed to change. Existing accounts with a
  matching email get linked automatically instead of creating a duplicate
  user. Google-only accounts (no password set) are blocked from the
  forgot-password flow, since there's no password to reset.
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
  (Excel export), python-jose (JWT), bcrypt, slowapi (rate limiting)
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

### Backend

```bash
cd backend
python -m venv ../venv          # or use the existing venv/ at repo root
../venv/Scripts/activate         # Windows
pip install -r requirements.txt
cp .env.example .env             # fill in real values, see below
```

Required env vars (`backend/.env`):

| Var | Required | Notes |
|---|---|---|
| `MONGO_URI` | yes | MongoDB Atlas connection string |
| `JWT_SECRET` | yes | must be ≥32 chars, generate with `python -c "import secrets; print(secrets.token_hex(48))"` |
| `MONGO_DB_NAME` | no (default `docintel_transport`) | |
| `GROQ_API_KEYS` | no | comma-separated, round-robined across calls |
| `PORT` | no (default `8000`) | |
| `NODE_ENV` | no (default `development`) | set `production` to disable `/docs`/`/redoc` |
| `FRONTEND_ORIGIN` | no (default `http://localhost:5174`) | CORS allow-list |
| `ADMIN_ORIGIN` | no (default `http://localhost:5175`) | CORS allow-list for the admin app |
| `ADMIN_1_PASSWORD` / `ADMIN_2_PASSWORD` | only for seeding | plaintext used once by the seed script, then only the bcrypt hash is stored |
| `GOOGLE_CLIENT_ID` | only for Google Sign-In | verifies Google ID tokens server-side; frontend needs the matching `VITE_GOOGLE_CLIENT_ID` in its own `.env`. Without it, Google Sign-In simply doesn't render — email/password login is unaffected |

Missing `MONGO_URI` or `JWT_SECRET` (or a `JWT_SECRET` under 32 chars) makes
the app refuse to start with a clear error — it will never silently boot
with a broken config.

Run the API:

```bash
cd backend
../venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --reload
```

Seed the two admin accounts (idempotent, safe to re-run):

```bash
cd backend
../venv/Scripts/python.exe -m app.scripts.seed_admin
```

### Frontend / Admin

```bash
cd frontend && npm install && npm run dev   # http://localhost:5174
cd admin && npm install && npm run dev      # http://localhost:5175
```

Both dev servers proxy `/api` to the backend (see each app's `vite.config.js`).

## Code quality

```bash
cd backend
../venv/Scripts/python.exe -m ruff check app
../venv/Scripts/python.exe -m black app --check
../venv/Scripts/python.exe -m isort app --check-only
../venv/Scripts/python.exe -m mypy app
```

All four are kept clean on every change.

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
- **Forgot password**: username+email match, not an emailed reset link —
  no possession-of-inbox proof. Inherited from the original app's design.
- **No deployment config yet**: no Dockerfile/Procfile in this repo —
  `NODE_ENV=production` disables debug-relevant behavior (Swagger docs,
  etc.) but the actual "how to run this on a server" step is still open.
- **Export History** is intentionally global (every user sees every
  export, any user can download any workbook from that one page) — this
  is a deliberate exception to the per-user isolation used everywhere
  else in the app, confirmed as a product decision.

## Security posture

JWT auth with `tokenVersion`-based session revocation, bcrypt password
hashing, NoSQL-injection-safe input validation (Pydantic-typed throughout,
no raw dict pass-through), rate limiting on auth + upload + workbook-creation
endpoints, per-user data isolation (documents/workbooks) with 404-not-403 on
cross-user access, security headers (CSP, HSTS, nosniff, frame-ancestors),
CORS restricted to explicit configured origins, admin routes gated by a
server-side role check that re-reads the DB (never trusts the JWT's role
claim). Audited across multiple passes this session — see git history for
specifics.

## Admin accounts

Two seeded admin accounts (Arjav Jain, Pratham Thatte) — passwords are never
hardcoded in source; the seed script reads them from `ADMIN_1_PASSWORD` /
`ADMIN_2_PASSWORD` env vars and only ever persists the bcrypt hash.
