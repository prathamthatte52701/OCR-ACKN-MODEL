# AckIntel AI

**Acknowledgement document intelligence.** Upload a Tax Invoice or Delivery Challan (photo or PDF), and AckIntel AI reads the document number and date for you, lets you check and correct them, and files everything into organised Excel workbooks.

It is a Windows desktop-style tool, built for one office PC: private per-user accounts, an admin approval step for new users, and an admin panel for support and oversight. The app itself runs only on that PC and is not published on the internet. It does use two online services: MongoDB Atlas stores the data, and Groq receives the header text of each document to pick out the number and date (never the image or the rest of the page).

## At a glance

**Upload** a document → **check** the number and date beside the original → **save** to Excel → find it in your yearly workbook, filed under the right month.

- Review and edit with the original file always in view
- Excel files that are written safely, even while you have them open
- Private accounts with admin approval and a full audit trail
- Clear flags for anything that looks unusual, so nothing slips through quietly
- A built-in chat between each user and the admins

## Screenshots

All screenshots use made-up demo accounts and sample documents. No real data is shown.

| | |
|---|---|
| ![My Documents: a user's processed Tax Invoices](docs/images/user-documents.png) | ![Review page: extracted fields beside the original document](docs/images/user-review.png) |
| **My Documents.** Filter by type, month and upload date, then save or download a whole page. | **Review.** Check or edit the number and date with the original always in view. |
| ![User chat panel with a conversation with an admin](docs/images/user-chat.png) | ![Admin dashboard with totals, a 30-day chart and recent activity](docs/images/admin-dashboard.png) |
| **Chat.** Ask an admin for help without leaving the page. | **Admin dashboard.** Totals, reading success and pending approvals. |
| ![Admin approvals queue](docs/images/admin-approvals.png) | ![Admin chat panel replying to a user](docs/images/admin-chat.png) |
| **Approvals.** New accounts wait here until an admin decides. | **Admin chat.** Reply to users and see unread counts. |

---

## Contents

- [What it does](#what-it-does)
- [How a document is read](#how-a-document-is-read)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Using the app](#using-the-app)
- [Chat](#chat)
- [Excel export rules](#excel-export-rules)
- [Data quality safeguards](#data-quality-safeguards)
- [Admin panel](#admin-panel)
- [Security](#security)
- [Operations](#operations)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## What it does

| Area | Details |
|---|---|
| **Reading documents** | Reads the **Tax Invoice No.** and **Reference No.** (Tax Invoice) or the **Delivery Challan No.** (Delivery Challan), plus the **date**. Accepts PDF, JPG, JPEG and PNG up to 5 MB each. PDFs can have up to 4 pages, and images up to 50 megapixels, which covers typical phone photos and scans. |
| **Photos** | Phone photos are cropped to the page, straightened (small tilts) before reading. |
| **Upload** | Single upload, or bulk upload of up to 10 files at once. |
| **Review** | The original file is shown next to the extracted values (zoom and pan for PDFs). Any value can be corrected by hand. |
| **Excel** | One workbook per year, one sheet per month. Save one document or a whole page at once. |
| **Accounts** | Email and password, or Google Sign-In. New accounts wait for admin approval. |
| **Chat** | A small text chat between each user and the admins, inside both apps. |
| **Admin panel** | Approve users, handle password requests, browse all documents and workbooks, read the audit log, answer chat, and run maintenance. |

Each person only ever sees their own documents, workbooks and export history.

## How a document is read

```text
 Upload (PDF / image)
        │
        ▼
 Page cleanup ── crops to the paper, straightens, only enhances rough scans
        │
        ▼
 OCR (PaddleOCR, on this PC) ── reads only the header at the top of the page
        │
        ▼
 Field extraction (Groq) ── a language model picks out the number(s) and the date
        │
        ▼
 Safety checks (plain Python, no AI) ── type check, format fixes, review flags
        │
        ▼
 You review and correct ── then save to Excel
```

Things worth knowing:

- Only the top part of the page is read. The numbers and date sit in the header, and ignoring the rest keeps reading fast and accurate.
- The first document after the app starts is slower, because the reading model takes up to a minute or two to load. After that it stays in memory.
- Documents are processed **one at a time**, on purpose, to keep memory use safe on a single PC. A bulk upload of 10 files takes about ten times as long as one file.
- The AI step is treated as untrusted. Whatever it returns is cleaned and checked before it is stored (see [Data quality safeguards](#data-quality-safeguards)).

## Architecture

```mermaid
flowchart LR
    subgraph PC["Office PC (Windows, localhost only)"]
        U["User app<br/>React, port 5174"]
        A["Admin app<br/>React, port 5175"]
        API["Backend API<br/>FastAPI, port 8000"]
        OCR["PaddleOCR<br/>header crop, one job at a time"]
        XLS[("backend/exports/<br/>per-user .xlsx workbooks")]
    end
    DB[("MongoDB Atlas<br/>users, documents, audit, chat<br/>files in GridFS")]
    G["Groq<br/>header text only"]

    U -->|"/api"| API
    A -->|"/api"| API
    API --> OCR
    API -->|"header text"| G
    API --> DB
    API --> XLS
```

- The two web apps are static builds served on this PC. They call the backend through `/api`.
- The backend keeps all records and uploaded files in MongoDB Atlas. Excel workbooks are real files on this PC.
- Only the text of the page header is sent to Groq. The image and the rest of the page never leave the PC.

## Quick start

This takes about 20 to 30 minutes the first time, most of it waiting for downloads. It sets up the whole app on one Windows PC. Everything runs locally; only the database lives in the cloud (MongoDB Atlas). After the first setup you only ever use `start.bat` and `stop.bat`.

**What you end up with:** a user app at <http://localhost:5174>, an admin app at <http://localhost:5175>, and a backend at <http://127.0.0.1:8000>, all running on your PC.

### 1. Install the prerequisites

| Tool | Version | Where to get it | Check it worked |
|---|---|---|---|
| Git | any recent | [git-scm.com](https://git-scm.com/download/win) | `git --version` |
| Python | **3.12** | [python.org](https://www.python.org/downloads/). Tick **"Add python.exe to PATH"** on the first installer screen. | `python --version` |
| Node.js | 20.19+ or 22.12+ | [nodejs.org](https://nodejs.org/) (use the LTS download) | `node --version` |

Open a new terminal (cmd or PowerShell) after installing, so the new tools are found. Run each check command above. If one says "not recognised", the tool is not on your PATH: reinstall it, or restart the terminal.

You also need two online accounts, both free:

- **MongoDB Atlas**, for the database (step 3).
- **Groq**, for reading the documents (step 4). Optional to start with: without a key, documents upload but cannot be read.

### 2. Download the code and create the Python environment

In a terminal, go to the folder where you want the project, then run:

```bash
git clone https://github.com/prathamthatte52701/OCR-ACKN-MODEL.git
cd OCR-ACKN-MODEL
python -m venv venv
```

If you forked the project, use your own fork's address in the first line. `python -m venv venv` creates a private Python environment in a folder called `venv`. Do it once; `setup.bat` and `start.bat` use it automatically.

### 3. Create the database (MongoDB Atlas)

1. Sign up at [mongodb.com/atlas](https://www.mongodb.com/atlas) and create a free **M0** cluster. Any cloud region works; pick one close to you.
2. **Database Access:** add a database user with a username and password. Note both. If the password has special characters such as `@`, `:` or `/`, either avoid them or URL-encode them in the connection string, or the connection will fail.
3. **Network Access:** add your PC's IP address (the **Add Current IP Address** button does this). If your IP changes, for example on another network, add the new one too.
4. **Connect, then Drivers:** copy the connection string. It looks like `mongodb+srv://<user>:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority`. Replace `<user>` and `<password>` with the ones from step 2.

You do not create the database or any collections yourself. The app creates `ackn_AI_model` and all its indexes the first time it starts.

### 4. Get a Groq API key (for reading documents)

Sign in at [console.groq.com/keys](https://console.groq.com/keys), create an API key and copy it. You can add more keys later, separated by commas, and the app spreads its calls across them.

Only the text of each document's header is ever sent to Groq. The image and the rest of the page stay on your PC.

### 5. Fill in `backend/.env`

Copy `backend/.env.example` to `backend/.env` (same folder, new name) and open it in any text editor. Fill in at least these:

| Setting | What to put |
|---|---|
| `MONGO_URI` | The connection string from step 3. |
| `JWT_SECRET` | A long random secret, at least 32 characters. Generate one by running `python -c "import secrets; print(secrets.token_hex(48))"` and pasting the result. |
| `GROQ_API_KEYS` | The key from step 4. Leave empty to add it later. |
| `ADMIN_1_NAME`, `ADMIN_1_EMAIL`, `ADMIN_1_PASSWORD` | Your first admin account. Use a strong password. You sign in with this email and password. |
| `ADMIN_2_NAME`, `ADMIN_2_EMAIL`, `ADMIN_2_PASSWORD` | The second admin. **Required:** the seed step in section 7 refuses to run unless both admin accounts are filled in. |

Everything else has a safe default. The full list is in [Configuration](#configuration). Never share `backend/.env` or commit it; git ignores it already.

### 6. Install and build: `setup.bat`

Double-click **`setup.bat`** in the project folder. It checks your tools, installs the backend packages (the first run downloads a lot and can take several minutes), then installs and builds the user app and the admin app. When it ends with **"Setup complete. Now run start.bat"**, it worked. If it stops with an `ERROR:` line, the message says what is missing. Fix that and run `setup.bat` again; it is safe to repeat.

Run `setup.bat` again after every update that changes code (see "Updating" below).

### 7. Create the admin accounts (once)

From the project folder, in a terminal:

```bash
cd backend
..\venv\Scripts\python.exe -m app.scripts.seed_admin
```

(In Git Bash, write `../venv/Scripts/python.exe` instead.) This creates both admin accounts from your `.env`. It is safe to run again: an account that already exists is left alone. After this you may delete the `ADMIN_*_PASSWORD` values from `.env`, because only the password hash is stored.

### 8. Start the app: `start.bat`

Double-click **`start.bat`**. It starts the three parts, each in its own minimised window titled "ACKN Backend", "ACKN User App" and "ACKN Admin App". **Do not close those windows**; use `stop.bat` instead. When everything answers, your browser opens the user app. The first start can take a minute.

Quick health check: open <http://127.0.0.1:8000/health> in a browser. `{"status":"ok"...}` means the backend is up and connected to the database.

### 9. First sign-in and first document

1. Open the **admin app**, <http://localhost:5175>, and sign in with the admin email and password from `.env`.
2. People who sign up in the user app wait as **pending**. Open **Approvals** in the admin app to approve them.
3. Approved users sign in at the **user app**, <http://localhost:5174>, and upload a Tax Invoice or Delivery Challan (image or PDF).
4. **The very first document is slow, often 30 to 90 seconds,** while the reading models load. Later ones are much faster.

| Part | Address | Port |
|---|---|---|
| User app | <http://localhost:5174> | 5174 |
| Admin app | <http://localhost:5175> | 5175 |
| Backend API | <http://127.0.0.1:8000> | 8000 |

All three listen on this PC only (`127.0.0.1`). Other computers cannot reach them.

### Daily use

- **Start:** double-click `start.bat`.
- **Stop:** double-click `stop.bat`. It only stops what `start.bat` started. A document that was being read is queued again at the next start.
- **Updating:** run `stop.bat`, then `git pull`, then `setup.bat`, then `start.bat`.

### If something goes wrong on the first run

| You see | Most likely cause and fix |
|---|---|
| `python` or `node` "is not recognized" | The tool is not installed or not on PATH. Reinstall it, tick the PATH option, open a new terminal. |
| `setup.bat`: "venv not found" | Step 2 was skipped. Run `python -m venv venv` in the project folder. |
| `setup.bat`: "backend\.env is missing or empty" | Step 5 was skipped. Copy `.env.example` to `.env` and fill it in. |
| "Missing MONGO_URI" or a `JWT_SECRET` error when starting | A required value in `backend/.env` is empty or too short (`JWT_SECRET` needs 32+ characters). |
| `/health` fails or the database cannot be reached | Check the connection string and password, and that your current IP is in Atlas **Network Access**. |
| "port is already in use" | Another program uses 8000, 5174 or 5175. Close it, or run `stop.bat` if it is a leftover of this app. |
| Admin sign-in fails | Run step 7 (`seed_admin`) and use the exact email and password from `.env`. |
| Documents stay "uploaded" and are never read | No Groq key set, or the key is wrong. See `backend/logs/app.log`. |

More cases are in [Troubleshooting](#troubleshooting). To run the apps in development mode with live reload instead, see [Development](#development).

## Configuration

All settings live in `backend/.env`. A missing or invalid required setting stops the app at start with a clear message. It never starts half-configured.

| Variable | Required | Default | What it does |
|---|---|---|---|
| `MONGO_URI` | **Yes** | — | MongoDB Atlas connection string. |
| `JWT_SECRET` | **Yes** | — | Signs login tokens. At least 32 characters. Generate one with `python -c "import secrets; print(secrets.token_hex(48))"`. |
| `MONGO_DB_NAME` | No | `ackn_AI_model` | Database name. Blank means the default. |
| `GROQ_API_KEYS` | No | — | One or more Groq keys, comma-separated. Calls are spread evenly across keys, and if one key is rate-limited or rejected the next is tried. |
| `GROQ_MODEL` | No | `openai/gpt-oss-120b` | Model used for extraction. The app never switches models on its own. |
| `GROQ_REASONING_EFFORT` | No | `high` | `low`, `medium` or `high`. Set it **blank** for a model that has no reasoning mode, so the setting is not sent. |
| `GROQ_MAX_TOKENS` | No | `2000` | Reply length limit, a whole number from 50 to 4000. If an answer is cut off it is retried once with double the limit (at most 4000); if it is still cut off the document fails with a message asking you to raise this value. |
| `OCR_DET_MODEL` | No | `PP-OCRv6_small_det` | PaddleOCR text **detection** model. Blank means the default. For the older v4 set use `PP-OCRv4_mobile_det`. |
| `OCR_REC_MODEL` | No | `PP-OCRv6_small_rec` | PaddleOCR text **recognition** model. Blank means the default. For the older v4 set use `en_PP-OCRv4_mobile_rec`. |
| `AUDIT_LOG_RETENTION_DAYS` | No | `365` | Audit entries older than this are deleted automatically. `0` keeps them forever. Whole number from 0 to 3650. |
| `CHAT_FILES_MAX_TOTAL_MB` | No | `75` | Total size cap for all chat attachments together, counted on the bytes actually stored (images are shrunk first). When it is full, new uploads are refused with "File storage is full. Please ask an admin." and text messages still work. Whole number from 1 to 100000. |
| `GOOGLE_CLIENT_ID` | No | — | Turns on Google Sign-In. Put the same value in `frontend/.env` as `VITE_GOOGLE_CLIENT_ID=<value>` (copy `frontend/.env.example`) before running `setup.bat`, so the sign-in button is built into the user app. Without it the Google button is simply not shown. |
| `FRONTEND_ORIGIN` | No | `http://localhost:5174` | Allowed browser origin for the user app. |
| `ADMIN_ORIGIN` | No | `http://localhost:5175` | Allowed browser origin for the admin app. |
| `ADMIN_1_NAME`, `ADMIN_1_EMAIL`, `ADMIN_1_PASSWORD` | Seeding only | — | First admin account. Also `ADMIN_2_*` for the second. The password is used once; only its hash is stored. |
| `ENABLE_DOCS` | No | off | `true` shows the API documentation pages (`/docs`, `/redoc`). Use on a developer machine only. |

### OCR models: download, offline and rollback

The reading step uses two PaddleOCR models, **PP-OCRv6 small** (`PP-OCRv6_small_det` and `PP-OCRv6_small_rec`). On a test of 14 header images it read as accurately as the older v4 mobile set (the difference was inside run-to-run noise) and was about 41% faster per image, using about 580 MB of memory.

- **Download.** `setup.bat` downloads them once at the end (about 30 MB, from Hugging Face by default). To do it by hand: `cd backend`, then `..\venv\Scripts\python.exe -m app.scripts.download_models`. If this step is skipped or fails, the models are downloaded the first time a document is read, and that first document is slow.
- **Where they are saved.** In your user profile: `C:\Users\<you>\.paddlex\official_models` (or the folder in `PADDLE_PDX_CACHE_HOME`, if you set it). Each model is one folder inside it.
- **A different download source.** Set the environment variable `PADDLE_PDX_MODEL_SOURCE` (for example `huggingface`, `modelscope` or `bos`) before running `setup.bat`, if the default one is slow or blocked on your network.
- **A PC with no internet.** On a PC that has internet, run the download step. Copy the whole `.paddlex` folder (`official_models` inside it, at least `PP-OCRv6_small_det`, `PP-OCRv6_small_rec` and `PP-LCNet_x1_0_doc_ori`) into the same place in the other PC's user profile. The app then finds the models and downloads nothing.
- **Go back to v4.** Put `OCR_DET_MODEL=PP-OCRv4_mobile_det` and `OCR_REC_MODEL=en_PP-OCRv4_mobile_rec` in `backend/.env` and restart. No code change. (The v4 models are downloaded the first time they are used.) A wrong model name stops the reading step with a clear message in the log and on the document, and it is tried again after a minute, so fixing the name needs no reinstall.

**Changing the Groq model:** set the new `GROQ_MODEL`, clear `GROQ_REASONING_EFFORT` if the model has no reasoning mode, restart the backend, then upload one test document to confirm it is read. If a model is retired by Groq, users see "The AI service is not set up correctly" and the log shows the reason.

**Audit retention note:** the first time the app starts with retention on, entries older than the limit are removed by MongoDB. Set `AUDIT_LOG_RETENTION_DAYS=0` before that first start if you want to keep older history.

## Using the app

### Getting an account

1. Sign up with email and password, or continue with Google.
2. The request waits for an admin. The sign-in page tells you your request was sent.
3. When an admin approves it, sign in again. You will see a short "you're approved" notice once.

**Using Google with an existing account.** The first time you continue with Google on an account that already has a password, the two are linked and you sign in with Google from then on. The old password is retired and earlier sessions end, which keeps the account tied to the person who owns the Google address. Admin accounts keep their password as well.

If a request is rejected, or access is later removed, the sign-in page shows the date and the reason the admin gave. A wrong password never reveals any of this.

**Forgot your password?** Use "Request password reset" on the sign-in page. An admin gives you a temporary password in person or by phone, and you choose a new one at your next sign-in. There is no reset email.

### Uploading and reviewing

1. Open **Upload**, choose **Tax Invoice** or **Delivery Challan**, and add a file. For several files, use bulk upload (up to 10).
2. Wait while the document is read. You can leave the page; progress is saved. For the best results with a phone photo, lay the page flat, keep the header in focus and use even light.
3. Check the values against the original shown beside them. Click **Edit** on any field to correct it.
4. Press **Save to Excel**.

**Reading problems are shown, not hidden:**

| Message | Meaning |
|---|---|
| **Number not read** | No number was found. Reprocess the document or type the number. The document cannot be saved to Excel until it has one. |
| **Looks incomplete** | The number is not in the usual shape (for example a digit is missing). It is kept exactly as read. Check it against the original. |
| **Please check this date** | The date is real but unlikely: more than a day in the future, or more than five years old. |

### Everyday pages

| Page | Use it to |
|---|---|
| **Dashboard** | See totals, recent documents and your document types at a glance. |
| **My Documents** | Browse by type, month and upload date. Save or download a whole page at once. |
| **View All Details** | See every document's extracted values in one table, sortable and paged. |
| **Export History** | Re-download the workbooks you have created. |
| **My Activity** | Review your own uploads, corrections, saves and deletes. |
| **Help** | Short answers to common questions. |

The user app has a left sidebar on screens 1024 px wide or more, and a slide-out menu below that. The button at the top left hides or shows the sidebar, and the app remembers your choice in this browser. The admin app works the same way.

## Chat

Both apps have a **Chat** button in the top bar. It opens a panel on the right (docked beside the page on wide screens, over the page on small ones).

- A user writes to an admin; an admin replies to a user. Messages are plain text, up to 1,000 characters.
- You can edit your own message for 15 minutes after sending it.
- A red badge shows unread messages. The panel and the badge refresh on their own while the tab is open.
- Users can pick the colour of their own messages (the palette button in the chat panel header).
- **Insert today's summary** (user app) pastes how many documents you processed today, by type, into the message box.
- Admins can delete one user's chat by age (**Clear chat…** in the chat panel). Deleting all chat is in **Maintenance** and asks for the admin's password.
- Sending is rate-limited, and the admin audit log records chat clean-ups as counts only, never message text.

**Files in chat.** The paperclip in the message box attaches one file to a message (the text is then optional).

- **Allowed:** JPG, PNG and WebP images up to 2 MB, and PDFs up to 3 MB. Exactly the limit is accepted; one byte more is not. Nothing else (no GIF, SVG, Word, Excel or zip).
- **Images are re-encoded.** The server shrinks anything larger than 1920 px on its longest side and saves a fresh copy with all metadata removed (camera data, GPS position, embedded comments). Animated images are refused. PDFs are stored exactly as sent and are never opened or rendered by the server.
- **Who sees what.** A user opens only the files in their own chat. Every admin can open every user's chat files.
- **Editing** changes the text only; the file cannot be replaced or removed by editing.
- **Expiry.** A file is deleted 30 days after it was sent. The message text stays and shows "File expired".
- **Storage.** All chat files together are capped (`CHAT_FILES_MAX_TOTAL_MB`, default 75 MB).
- **Not supported:** more than one file per message, paste or drag and drop (use the paperclip), and virus scanning (see Security).
- **Limits.** 20 file sends per hour for a user, 60 for an admin; these also count toward the normal message limits.
- Deleting a user, clearing a chat (by age or all of it) or running the wipe script deletes the chat files too. The clear dialogs show how many messages and files will go.

## Excel export rules

- Each user gets **one workbook per year**, with **one sheet per month**.
- A document is filed by **its own date**, not by the day you upload or save it. A paper dated 20 December and saved in January goes into the December sheet of the earlier year.
- Each row has four columns: **Document Type, Number, Date, Timestamp**.
- A workbook name is unique for each user. "Bills", "bills" and "Bills.xlsx" count as the same name, so an existing workbook is never replaced by accident. If the name is taken you see "A workbook with this name already exists." and can pick another.
- **Save Again** replaces the earlier row for that document. It does not add a duplicate.
- When a new year starts, the old workbook is archived and you are asked to name the new one. Old workbooks stay on disk, untouched.
- Writes are safe if the workbook is open in Excel: the file is written aside and swapped in, and if Excel holds it you are told it is busy and nothing is lost.
- **Save All** saves one page of documents. Each document succeeds or fails on its own, and failures are listed with the reason.

**Rules at save time**

| Situation | What happens |
|---|---|
| No number | **Blocked.** For a Delivery Challan the number must be present. For a Tax Invoice at least one of Tax Invoice No. or Reference No. must be present. |
| No date, or an odd date | Saved, with a notice. A missing date uses the save date. |
| Same type, number and date as another saved document | **Saved, with a warning** to check it is not a duplicate. |
| Document edited while it was being saved | The row may hold the earlier values. You are told to press Save Again, and the document is not marked as exported. |

## Data quality safeguards

The AI is helpful but not trusted. Every value goes through plain code before you see it:

- **Type and length checks.** Only text (or a whole number) of at most 64 characters is accepted. Lists, objects, true/false and huge values are dropped, so the field is left empty for you to fill in. Nothing is guessed.
- **Date rules.** Only a real calendar date between 2000 and 2100 is accepted.
- **Look-alike fixes.** Common OCR mix-ups (a letter read in place of a digit) are corrected only when the result then passes the format check. A correction never invents digits.
- **Review flags.** Values that are read but look wrong are flagged and never changed. These cover numbers of the wrong length, and dates far in the future or the past.
- **Your edits win.** Typing a value clears its flag and marks the document as edited.

## Admin panel

Open <http://localhost:5175> and sign in with an admin account. The dashboard, Users, Approvals and Password requests pages refresh quietly in the background while the tab is visible, so new requests appear without a reload. The refresh pauses while a dialog is open or a request is running, and backs off if the server stops answering.

| Section | Purpose |
|---|---|
| **Dashboard** | Totals, a 30-day chart, reading success, recent activity, and one-click approval of the oldest pending requests. |
| **Users** | Search and view users, change the email of a password account (accounts that sign in with Google use their Google address), delete a user. |
| **Approvals** | Approve, reject (with an optional reason), revoke or re-approve. This includes people who signed up with Google. |
| **Password requests** | See who asked for a reset and set a temporary password. |
| **Documents, Workbooks** | Browse every user's data. Admin access to another user's data is written to the audit log. |
| **Chat** | The chat button in the top bar opens the admin chat panel. Reply to users, pick a thread, and clear one user's chat by age. |
| **Activity** | The audit log. |
| **Orphaned files** | Files left behind by a failed cleanup, for follow-up. |
| **Maintenance** | Storage and uptime, plus a protected "danger zone" for permanent bulk deletes. These need a typed confirmation phrase and your own password, entered twice. |

Admins are created from the environment settings by the seed script and cannot be rejected from the panel. An admin who forgets their password uses `backend/app/scripts/reset_admin_password.py`.

## Security

- **Approval gate.** Every protected route checks the account is approved, even for a token issued earlier.
- **Sessions.** Login tokens last 7 days and are cancelled immediately by a password change, an email change, a rejection, or linking Google sign-in to a password account (admin accounts are not affected by the link).
- **Passwords.** 8 to 64 characters with an uppercase letter, a lowercase letter, a number and a special character, no spaces, and not containing the username or email name. Stored as bcrypt hashes.
- **Data isolation.** Every document, workbook and export query is limited to its owner. Another person's item looks like it does not exist.
- **Admin routes.** The role is re-read from the database on every request, never taken from the token.
- **Rate limits** on sign-in, signup, password-reset requests, upload and workbook creation.
- **Upload safety.** Size, file type and image-size limits are checked before the file is processed, so a small file cannot expand into gigabytes of memory.
- **Browser protections.** Strict security headers and a fixed list of allowed origins.
- **Chat files.** The file type is decided from the file's bytes, never its name or the browser's claim. Images are re-encoded (which drops hidden data and anything appended to the file) and checked for oversized dimensions and animation. A file is served only with its own validated type, `nosniff`, `Content-Security-Policy: default-src 'none'; sandbox` and `Cache-Control: no-store`; images are shown inline and PDFs as downloads. A stranger, an unknown id and a malformed id all get the same "not found". **There is no antivirus scan**: a PDF is stored as sent, so treat PDFs from outside like any other download.
- **Secrets stay out of the log.** Keys, tokens and passwords are masked before anything is written to it.
- **Google Sign-In.** The Google token is verified on the server against your client ID, and the Google email must be verified. A new Google user still waits for approval.
- **Downloads.** A user's workbook download is served only from the exports folder and only with the owner's user ID in its file name, so a crafted name cannot reach another file.
- **Local only.** The servers listen on `127.0.0.1`. The API documentation pages are off unless `ENABLE_DOCS=true`.
- **Login token storage.** The browser keeps the login token in local storage, so any script injected into the page could read it. Both apps avoid inserting raw HTML, and tokens end at once on password change, rejection or removal. Keep the PC itself trusted.
- **Secrets in the repository.** `backend/.env` is ignored by git and never committed. `backend/.env.example` holds names only. Test files contain obviously fake keys used to test log masking.

## Operations

### Logs

The server writes to `backend/logs/app.log`. The file rotates at 10 MB, is kept for 10 days, and older files are compressed. It can contain email addresses and document details, so do not share it publicly.

```powershell
Get-Content backend\logs\app.log -Tail 100 -Wait
```

### Maintenance scripts

Run these from the `backend` folder with `../venv/Scripts/python.exe -m app.scripts.<name>` (in cmd use backslashes: `..\venv\Scripts\python.exe`). Scripts that change data also require `--db <name>`, which must equal `MONGO_DB_NAME` (or the default name). Scripts that change data do nothing unless you ask for it explicitly.

| Script | Purpose |
|---|---|
| `seed_admin` | Create the admin accounts from the environment settings. Safe to repeat: an admin whose email already exists is left unchanged. |
| `reset_admin_password` | Set a new password for an admin. |
| `migrate_user_status` | One-time step for an older database so existing users stay approved. Run with `--dry-run` first. |
| `find_duplicate_workbooks` | Read-only report: lists any user who has two workbook records pointing at the same file. Changes nothing. |
| `cleanup_orphan_corrections` | Remove correction history whose document no longer exists. Needs `--db <name>`. Dry run by default; add `--apply` to delete. |
| `wipe_all_except_admins` | Fresh start: remove all users, documents, files and workbooks except the admins. Needs `--db <name>`. Dry run by default; applying needs `--apply --i-have-a-backup`. Stop the app and take a `mongodump` backup first. |

### Chat files and storage

Chat attachments live in their own database area (`chatfs`), separate from documents, so the Orphaned files page and the document storage numbers never include them. The Atlas free tier is 512 MB in total, shared with documents, so keep `CHAT_FILES_MAX_TOTAL_MB` modest. An hourly background job (and one run at start) deletes files older than 30 days, at most 200 per run, and retries any delete that failed.

### Backups

Take regular `mongodump` backups of the database, and copy the `backend/exports/` folder, which holds the Excel workbooks. Each workbook file is named `<userId>_<workbook name>.xlsx`, so every user's files are easy to tell apart. Uploaded documents are stored inside the database itself.

## Development

**Stack**

| Layer | Technology |
|---|---|
| Backend | FastAPI, PyMongo Async (async MongoDB), PaddleOCR (CPU), Groq, PyMuPDF, openpyxl, PyJWT, bcrypt, slowapi |
| User and admin apps | React, Vite, Tailwind, TanStack Query, Zustand |
| Database and files | MongoDB Atlas, with documents stored in GridFS |

**Layout**

```text
backend/    FastAPI app, one folder per feature under app/features
            (auth, documents, ocr, excel, admin, chat)
frontend/   User app (port 5174)
admin/      Admin app (port 5175)
docs/       Extra notes, such as the admin screen map
```

**Developer mode** (for the developer only, not for daily use; `--reload` can hang on Windows):

```bash
cd backend && ../venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev
cd admin && npm install && npm run dev
```

Both dev servers forward `/api` to the backend.

**Code quality.** These four checks are kept clean on every change:

```bash
cd backend
../venv/Scripts/python.exe -m ruff check app
../venv/Scripts/python.exe -m black app --check
../venv/Scripts/python.exe -m isort app --check-only
../venv/Scripts/python.exe -m mypy app
```

The frontend and admin apps are checked with `npm run lint` and `npm run build`.

**Tests**

```bash
cd backend
../venv/Scripts/python.exe -m pytest app
```

The backend suite has close to 800 test functions (more cases once parametrised) covering sign-in and approval, per-user isolation, the reading pipeline, Excel saving, admin actions and the maintenance scripts. A full run is slow (hours) because the tests use a real MongoDB Atlas database (a separate `_test` one), so each step is a network round trip. Running one folder or file is much faster, for example `pytest app/features/auth`.

Tests are safe by design. `backend/conftest.py` forces a database whose name ends in `_test` and a separate test-only signing secret, and stops immediately if that is ever not the case. Set `ACKN_TEST_DB` to choose a different `_test` database name, for example to run two test sessions side by side.

The frontend and admin apps have small plain Node scripts in `frontend/tests/` and `admin/tests/`. Run one with `node frontend/tests/<file>.cjs`. Some of the frontend scripts drive a browser with Playwright and need the dev server running.

## Troubleshooting

| Problem | What to do |
|---|---|
| The app does not start | Run `stop.bat`, then `start.bat`. If a port is in use by another program, the script names it. |
| "Missing MONGO_URI" or a `JWT_SECRET` error | Fill in `backend/.env`. See [Configuration](#configuration). |
| Cannot reach the database | Check the internet connection and that this PC's address is allowed in the Atlas network access list. If the connection still times out, try another network. |
| Documents stay in "uploaded" | Check `backend/logs/app.log`. A missing Groq key or a retired model is reported there. |
| "The AI service is not set up correctly" | Check `GROQ_API_KEYS` and `GROQ_MODEL`, then restart. |
| "The AI answer was cut off" | Press **Reprocess**. If it repeats, raise `GROQ_MAX_TOKENS` (up to 4000) in `backend/.env` and restart. |
| A save says the workbook is busy | Close the workbook in Excel and save again. |
| A page looks old after an update | Run `setup.bat` again so both apps are rebuilt. |
