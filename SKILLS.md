---
name: dev-workflow
description: Standard working style for this repo — explore, plan, code, test, verify, commit, cleanup.
---

# Dev Workflow

Follow this order for every task in this repo, big or small.

1. **Explore** — read the relevant existing code first. Don't guess how something works, check it.
2. **Plan** — figure out the smallest correct change before writing code. For a multi-step task, list the steps.
3. **Code** — make the change.
4. **Test** — actually run something real. Don't claim it works without running it. Use these exact commands:
   - Backend tests: `cd backend && PYTHONPATH=. venv/Scripts/python.exe -m pytest app/features/<area>/test_*.py -v`
   - Backend full suite: `cd backend && PYTHONPATH=. venv/Scripts/python.exe -m pytest -v`
   - Frontend build check: `cd frontend && npx vite build --mode development`
   - Admin build check: `cd admin && npx vite build --mode development`
   - E2E flow tests: `cd frontend && node e2e/<test_file>.cjs` (raw Playwright scripts, no runner — read the file first, some need env vars for login credentials)
5. **Verify** — check the change didn't break anything that used to work. Re-run old tests for any file you touched, not just new ones.
6. **Refine** — if a test fails or something looks off, fix it now. Don't leave a feature half-working.
7. **Commit** — only when explicitly asked, never on your own. Message must be professional but plain, simple English — no jargon, no buzzwords, say what changed and why in one or two lines.

## Answer style

During work, keep responses normal — short updates, no forced padding. Once a task is actually finished, the final report/summary should be medium length, in simple English: explain what changed, what was tested, and the result, in a few clear sentences — not a one-line summary, but also not a wall of text. Avoid unnecessary technical jargon; explain things the way you'd explain them to someone who knows the project but not every internal detail.

## Git rules

- Never commit unless the user explicitly asks.
- Never force-push, never use `--no-verify`, never skip hooks, unless the user explicitly says to.
- Before any destructive git command (`reset --hard`, `checkout --`, `clean -f`), run `git status` first and make sure nothing important gets lost.
- Prefer new commits over amending existing ones, unless told otherwise.
- Always create commits with a clear message (see Commit step above) — no vague messages like "fix stuff" or "updates".

## End-of-task cleanup (when the user says the session/feature is done)

Do these in order, every time work wraps up:
1. `git push` — commit and push the finished work.
2. Clean the test data created during that session's testing (throwaway test accounts, test documents, test uploads) from the database — but never touch the real admin accounts or real production-relevant data.
3. Stop every server and background process started during the session (backend uvicorn, frontend/admin vite dev servers, any test scripts left running) — leave nothing running in the background.
