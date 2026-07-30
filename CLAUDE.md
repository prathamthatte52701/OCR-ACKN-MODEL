# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AckIntel AI — OCR extraction of Number/Date from Tax Invoice and Delivery
Challan acknowledgement documents (image or PDF). Per-user auth, manual
correction, bulk upload, Excel export with yearly/monthly auto-organization,
admin panel with cross-user CRUD + telemetry. Python/FastAPI rewrite of an
earlier Node/Express app (see `ANALYSIS.md` for the full pivot mapping —
Mongoose→Pydantic, Tesseract→PaddleOCR, exceljs→openpyxl, etc.).

## Stack

- **Backend**: FastAPI, Motor (async MongoDB), PaddleOCR (CPU-only), Groq
  (field extraction via Jinja2 prompts), PyMuPDF (PDF), openpyxl (Excel),
  python-jose (JWT), bcrypt, slowapi (rate limiting)
- **Frontend**: React + Vite + Tailwind + TanStack Query + Zustand
- **Admin**: separate React + Vite app, same backend, role-gated
- **Database**: MongoDB Atlas, file storage via GridFS (same cluster)

## Project layout

```
backend/    FastAPI app — app/features/{auth,documents,ocr,excel,admin}
frontend/   Main user-facing React app (port 5174)
admin/      Admin panel React app (port 5175)
```

## Commands

### Backend

```bash
cd backend
../venv/Scripts/activate                                    # Windows
pip install -r requirements.txt
cp .env.example .env                                         # fill MONGO_URI, JWT_SECRET, etc.

../venv/Scripts/python.exe -m uvicorn app.main:app --port 8000 --reload
../venv/Scripts/python.exe -m app.scripts.seed_admin          # idempotent, seeds 2 admin accounts
```

Code quality gate (all four kept clean on every change):

```bash
cd backend
../venv/Scripts/python.exe -m ruff check app
../venv/Scripts/python.exe -m black app --check
../venv/Scripts/python.exe -m isort app --check-only
../venv/Scripts/python.exe -m mypy app
```

Tests: `pytest`/`pytest-asyncio` are dependencies but there's no
`pytest.ini`/`conftest.py`. `app/features/ocr/test_extraction.py` is the one
existing suite — plain `test_*` functions with `assert`, runnable via
`pytest app/features/ocr/test_extraction.py` or directly with
`python -m app.features.ocr.test_extraction`.

### Frontend / Admin

```bash
cd frontend && npm install && npm run dev     # http://localhost:5174
cd admin && npm install && npm run dev        # http://localhost:5175
npm run lint     # eslint . — no separate frontend test runner (no vitest/jest)
npm run build
```

Both dev servers proxy `/api` → the backend (see each app's `vite.config.js`).
`frontend/src/api/client.js` and `admin/src/utils/api.js` both hardcode
`baseURL: '/api'` — `VITE_API_URL` was tried and deliberately reverted
(commit `d96a569`); don't reintroduce env-based API URLs without checking
current intent first.

### E2E tests

`frontend/e2e/*.cjs` — raw Playwright scripts (no `@playwright/test` runner,
no assertion library). Run directly with `node frontend/e2e/<file>.cjs`
against a running dev server. Pattern: launch headless Chromium, seed data
via direct `page.request.post(...)` calls to the API (bypassing the UI) using
a bearer token from a login call, drive the UI, push `{step, ok, detail}`
into a `results` array, print a `=== SUMMARY ===` at the end. No shared
helper module — each file is self-contained. `test_admin.cjs` needs
`ADMIN_1_EMAIL`/`ADMIN_1_PASSWORD` env vars and takes screenshots at each
step. New feature tests should follow this exact shape.

## Required env vars (`backend/.env`)

`MONGO_URI` and `JWT_SECRET` (≥32 chars) are required — the app calls
`sys.exit` with a clear error at import time (`app/core/config.py`) rather
than silently booting broken. Optional: `MONGO_DB_NAME`, `GROQ_API_KEYS`
(comma-separated, round-robined), `PORT`, `NODE_ENV` (`production` disables
`/docs`/`/redoc`/`/openapi.json`), `FRONTEND_ORIGIN`, `ADMIN_ORIGIN`,
`ADMIN_1_PASSWORD`/`ADMIN_2_PASSWORD` (seed-only, plaintext used once then
discarded — only the bcrypt hash persists).

## Architecture

### Request lifecycle & shared primitives

- `app/main.py` wires everything: CORS (explicit allow-list, never `*`),
  `SecurityHeadersMiddleware`, `SlowAPIMiddleware`, a `RequestValidationError`
  handler that remaps malformed-`ObjectId` path params to a clean 400 (rest
  stays FastAPI's normal 422), and `lifespan()` (Mongo connect + index
  creation, background-task recovery of interrupted uploads — see Known
  Gotchas).
- Every Mongo-backed Pydantic model extends `CamelModel`
  (`app/core/base_model.py`): snake_case Python fields, camelCase on the
  wire via `alias_generator=to_camel` + `populate_by_name=True` — this is
  why the frontend never needed renaming during the Node→Python pivot.
  `MongoBaseModel` adds `id`/`created_at`/`updated_at`.
- **Auth/session model is JWT + `tokenVersion` revocation, not stored
  sessions.** `sign_token(user_id, token_version, role)` embeds
  `{userId, tokenVersion, role, exp}` (`app/core/security.py`, HS256,
  7-day TTL). `get_current_user` (`app/features/auth/dependencies.py`)
  decodes the token, then **re-reads `tokenVersion`/`role` from the DB**
  and 401s on any mismatch — this is how password-change/reset invalidate
  every other issued token. `require_admin` similarly never trusts the JWT's
  role claim, always re-reads from DB.
- **Per-user data isolation is enforced by convention, not middleware**:
  every documents/workbooks query in `router.py` files explicitly filters
  `{"userId": current_user.id}`, and ownership lookups 404 (never 403) on
  cross-user access so existence isn't leaked. `GET /export-history` and its
  workbook-download route are the *one deliberate* exception — intentionally
  global across all users (confirmed product decision, see the comment
  block above that route in `excel/router.py`). When adding a new
  documents/workbooks endpoint, default to scoping by `userId` unless you
  have equally explicit confirmation it should be global.
- Most DB writes in `router.py` files use **raw camelCase dicts directly**
  against Motor collections, not the Pydantic models in each feature's
  `models.py` — those model classes describe the read-shape/schema but
  are not enforced on every write. Don't assume adding a field to a
  `models.py` class changes what's actually persisted; the raw-dict insert
  sites are the real contract.
- Indexes are created idempotently on every startup in
  `app/core/database.py::_ensure_indexes` — add new indexes there, not in
  a migration script (none exists).

### OCR pipeline (the core value path)

`documents/router.py` → `ocr/pipeline.py::process_document` →
`ocr/preprocessing.py` (header crop / PDF text-or-image) →
`ocr/paddle_runner.py::run_ocr` (blocking, via `asyncio.to_thread`) →
`ocr/ai_extraction.py::extract_header` (Groq, Jinja2-templated
per-document-type prompts) → `ocr/extraction.py` (pure-Python
character-confusion correction + confidence scoring, ported 1:1 from the
old app's post-processing, no AI involved).

- Only the **top 28%** of the page (`HEADER_CROP_RATIO` in
  `preprocessing.py`) is ever OCR'd — extraction is header-only by design,
  not full-document OCR.
- A single **process-wide `asyncio.Lock`** (`pipeline.py::_ocr_lock`)
  serializes all OCR calls — one job at a time, by design, to protect
  memory on a single-machine deployment. This is why bulk uploads process
  strictly sequentially (`documents/router.py::_run_sequentially`), not
  concurrently — a 10-file batch takes ~10× one file's time.
- `paddle_runner.py` uses a **lazy singleton** PaddleOCR instance (model
  load is the expensive part — 30-90s). CPU thread env vars
  (`OMP_NUM_THREADS` etc., capped at 6) are set via `os.environ.setdefault`
  **before** paddle/numpy import — measured fix for concurrent GET requests
  starving during an OCR job. `enable_mkldnn=False` and
  `use_doc_orientation_classify=False` are deliberate (mkldnn throws on
  this build; orientation classify costs time and is currently unused) —
  read the module docstring before changing OCR config, several settings
  encode hard-won tuning, not defaults.
- `extraction.py`'s character-confusion correction (`_CONFUSION_MAP`,
  `correct_number_format`, `correct_date_format`) is validated behavior —
  don't touch its logic when working on anything upstream (preprocessing)
  or downstream (router `/correct` endpoint); it's covered by
  `test_extraction.py`.
- `OCR_TIMEOUT_SECONDS_IMAGE`/`_PDF` live as constants in `paddle_runner.py`
  directly, **not** wired through `app/core/config.py`/env vars.

### Excel export

`excel/service.py` is pure file I/O (no rollover orchestration): workbooks
are per-user physical `.xlsx` files on disk at `backend/exports/`, named
`{userId}_{workbookFilename}.xlsx` (the userId-prefix convention is applied
by callers in `excel/router.py`, not centralized in `service.py` itself —
replicate it exactly if you add a new caller). Concurrency-safe via a
double lock: in-process `asyncio.Lock` + cross-process `FileLock` on a
`.lock` sidecar (30s timeout), writes go to a `.tmp{pid}.xlsx` then
`os.replace()` for atomicity against a workbook open in Excel. One
worksheet per month, named by the **document's own extracted `date`**, not
upload/export time (`month_from_date`). Rows have **no stable ID** —
`_append_row_sync` uses plain `sheet.append()`, so anything that needs to
find/modify a specific row later must match by
`(documentType, formatted-number, date)` tuple. Year rollover
(`Workbook.isActive`/`archivedAt`) is orchestrated in `excel/router.py`
(`POST /new-excel-file`, the year-mismatch 409 in `POST /{doc_id}/save`),
not in `service.py`.

### Frontend/Admin

React Router v7 + TanStack Query (server state) + Zustand (auth token,
small UI state) — no Redux, no Context for data. `useSearchParams` is the
established pattern for filter state on list pages (see
`DocumentsPage.jsx`'s `number`/`date`/`type` params) so filters are
shareable/bookmarkable; follow it for new filters rather than local state.
No table library is installed — the existing plain-`<table>` pattern in
`admin/src/pages/AdminDocumentsPage.jsx` is the reuse point for any new
tabular view rather than adding one. Destructive account-wide actions use a
typed-confirmation-phrase dialog pattern (see `ProfilePage.jsx`'s
`HardDeleteEverythingDialog`), distinct from the shared one-click
`GlobalConfirmDialog`/`confirmAction()` (`store/dialogStore.js`) used for
lighter confirmations.

## Known gotchas / gaps (read before touching these areas)

- **Startup recovery blocks the app.** `recover_interrupted_uploads()`
  (`documents/router.py`) runs on every restart to requeue documents stuck
  in `uploadStatus: "uploaded"`. Verify current `main.py` for whether this
  still runs inline before `yield` in `lifespan()` (blocking `/health` and
  every other route until all stuck documents finish a full sequential OCR
  pass) or has been moved to a background task — this has been an active
  fix target.
- **PaddleOCR crash containment is weaker than it looks.** `run_ocr`'s
  try/except catches normal Python exceptions, but a native-level
  segfault in the C++ backend takes down the worker thread and cannot be
  caught in-process — documented explicitly in `paddle_runner.py`'s module
  docstring. No subprocess isolation exists today (deliberate tradeoff,
  not an oversight).
- **Forgot-password has no email/OTP step** — username+email match only,
  inherited from the old app's design (see README "Known limitations").
  Don't assume any out-of-band verification channel exists anywhere in
  this app when designing new confirmation flows.
- **No deployment config** (`render.yaml` exists at repo root but no
  Dockerfile/Procfile) — `NODE_ENV=production` only disables debug
  surfaces, it doesn't define how the app actually gets deployed.
- `backend/requirements.txt` has a `--extra-index-url` pin for
  paddlepaddle's Linux CPU wheels — required for Render/Docker/CI even
  though Windows installs fine without it. Don't remove it.
