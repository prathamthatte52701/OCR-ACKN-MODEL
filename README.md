# AckIntel AI — Acknowledgement Document Intelligence

OCR-based extraction of Number and Date from Tax Invoice / Delivery Challan
acknowledgement documents (image or PDF), with per-user auth, manual
correction, bulk upload, Excel export with yearly/monthly auto-organization,
and an admin panel with cross-user CRUD + telemetry.

Python/FastAPI rewrite of an earlier Node.js/Express app — same product,
new stack: FastAPI, MongoDB (Motor), PaddleOCR, Groq, React/Vite.

## Recent features

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

### Backend

```bash
cd backend
python -m venv ../venv          # or use the existing venv/ at repo root
../venv/Scripts/activate         # Windows
pip install -r requirements-dev.txt   # exact runtime pins + ruff/black/isort/mypy/pytest
                                       # (production installs requirements.txt only)
cp .env.example .env             # fill in real values, see below
```

Required env vars (`backend/.env`):

| Var | Required | Notes |
|---|---|---|
| `MONGO_URI` | yes | MongoDB Atlas connection string |
| `JWT_SECRET` | yes | must be ≥32 chars, generate with `python -c "import secrets; print(secrets.token_hex(48))"` |
| `MONGO_DB_NAME` | no (default `docintel_transport`) | |
| `GROQ_API_KEYS` | no | comma-separated, round-robined across calls |
| `ENABLE_DOCS` | no (default off) | `true` exposes `/docs`, `/redoc`, `/openapi.json` (developer machines only) |
| `FRONTEND_ORIGIN` | no (default `http://localhost:5174`) | CORS allow-list |
| `ADMIN_ORIGIN` | no (default `http://localhost:5175`) | CORS allow-list for the admin app |
| `ADMIN_1_NAME` / `ADMIN_1_EMAIL` / `ADMIN_1_PASSWORD` and the same three for `ADMIN_2_` | only for seeding | the seed script reads the admin identities from here (none are in source); the password plaintext is used once, then only the bcrypt hash is stored |
| `GOOGLE_CLIENT_ID` | only for Google Sign-In | verifies Google ID tokens server-side; frontend needs the matching `VITE_GOOGLE_CLIENT_ID` in its own `.env`. Without it, Google Sign-In simply doesn't render — email/password login is unaffected |

Missing `MONGO_URI` or `JWT_SECRET` (or a `JWT_SECRET` under 32 chars) makes
the app refuse to start with a clear error — it will never silently boot
with a broken config.

Run the API:

```bash
cd backend
../venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --reload
```

Seed the two admin accounts from the `ADMIN_*` env vars (idempotent, safe to re-run):

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

## Tests

```bash
cd backend
../venv/Scripts/python.exe -m pytest app
```

`backend/conftest.py` forces the database name to `<name>_test` and a
test-only JWT secret before the app loads, and aborts if the DB name does not
end in `_test` — the suite never touches real data. About 190 tests cover
the approval gate, isolation (two-user IDOR checks on every documents/excel
route), admin audit logging, passwords, field/upload limits, JWT and the
pinned requirements. Frontend and admin have no unit-test runner (`npm run
lint` and `npm run build` only).

## Docker

```bash
cp backend/.env.example backend/.env   # fill JWT_SECRET, GROQ_API_KEYS, admin vars
docker compose up --build              # MongoDB + backend on http://localhost:8000
```

The frontend and admin apps run separately (`npm run dev`) and proxy `/api` to
the backend. First start takes a minute while PaddleOCR loads its models.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request: backend
`ruff`, `black`, `isort`, `mypy` and `pytest` (against a throwaway MongoDB),
and `lint` + `build` for both React apps.

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
- **Minimal deployment config**: `render.yaml` starts uvicorn on `0.0.0.0`;
  there is no Dockerfile/Procfile. Swagger/ReDoc/openapi.json are off
  everywhere unless `ENABLE_DOCS=true`.
- **Google linking**: an existing password account that signs in with Google
  is linked automatically (Google verified the email).
- **Admin forgot-password** has the same username+email reset as users.
- **7-day tokens**: JWTs last 7 days and are revoked only by a `tokenVersion`
  bump (password change, reject).
- **My Activity** only shows delete / file-purge / export events — uploads,
  OCR results and corrections are not written to the audit log.

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
