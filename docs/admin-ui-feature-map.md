# Admin UI redesign - feature map

The four mockups are a **style** reference. Every element below is mapped to a real feature/data source
or dropped. Nothing is shown that the app cannot back with real data.

Legend: KEEP = exists as is, ADAPT = exists, shown differently, NEW-API = needs a small read-only admin-only
aggregate endpoint, DROP = no real feature, not shown.

## Shell (all pages)

| Mockup element | Real feature / data source | Decision |
|---|---|---|
| Brand "ACKN OCR" + logo | static text/svg (ours) | KEEP |
| Sidebar: Dashboard, Users, Documents, Workbooks | existing routes `/`, `/users`, `/documents`, `/workbooks` | KEEP |
| Sidebar: Approvals | the pending-approvals view of Users (`/users` pending tab) with the real pending count badge | ADAPT (route `/approvals` = pending-only Users view, same API) |
| Sidebar + Users tab: Password requests | `GET /admin/password-requests` (`requests`, `openCount`); own tab (`/password-requests`) with its own badge, separate from Pending/Rejected. Table shows username, email, note (plain text), requested date, status. Actions: Set temp password (`POST .../{id}/temp-password`, admin types or generates it; shown only while the dialog is open) and Dismiss with confirm (`POST .../{id}/dismiss`) | ADD (admin-handled password reset) |
| Sidebar: Exports | no admin Exports page exists (export rows only appear inside a user's detail page) | DROP |
| Sidebar: Maintenance | existing `/maintenance` | KEEP |
| Sidebar: Settings | no such page | DROP |
| (not in mockup) Logs, Orphaned Files | existing, must stay reachable | KEEP, shown as "Activity" (`/logs`) and "Orphaned files" |
| Sidebar footer "All services running" + "Open Maintenance" | only if computed from a real check: `GET /admin/system` (DB ping + OCR lock) | ADAPT (shows real status; red/amber when a check fails) |
| Top bar search "Search users, documents..." | no global search; user search is real (new `q` param on `GET /admin/users`) | ADAPT ("Search users by name or email", goes to `/users?q=`) |
| Notification bell + red badge | `pendingCount` + `passwordRequestCount` of `GET /admin/users`, links to Approvals (or Password requests when only requests are waiting); no badge at 0 | ADAPT |
| (not in mockup) Chat button + unread badge | `/api/chat/*` (`GET /chat/unread` polled while the tab is visible); opens the admin chat panel on the right: user picker, thread, reply box, edit within 15 minutes, "Clear chat..." (by age, one user). Global "delete all chat" lives in Maintenance (typed word + password) | ADD |
| (not in mockup) Sidebar hide/show button | top-left toggle; state kept in the browser (`ackn.admin.sidebarHidden`) | ADD |
| (not in mockup) Quiet auto-refresh | Dashboard, Users, Approvals and Password requests re-fetch in the background while the tab is visible; paused while a dialog is open or a request is running; backs off after repeated failures | ADD |
| Admin name + role + avatar chevron | `useAdminAuth().user`; menu: Profile, Log out | KEEP (initials circle, colour from user id) |
| Photos / avatars | the app has none | ADAPT (coloured initial circles, deterministic from user id) |

## Dashboard (`GET /admin/telemetry`, extended)

| Mockup element | Source | Decision |
|---|---|---|
| "Welcome back, Admin" + subtitle | admin username | KEEP |
| Tabs Overview / Documents / Users / Activity | no such views | DROP |
| Stat: Total users (+6.2% this month, sparkline) | `totalUsers`, `trends.users`, `series.users` (new users per day) | KEEP/NEW-API (series) |
| Stat: Pending approvals (3, live dot) | `pendingUsers.count` | KEEP (no sparkline: no history exists) |
| Stat: Documents processed (+12.4% this week, sparkline) | `documentsByStatus.processed`, `trends.documents`, `series.documents` | KEEP/NEW-API |
| Stat: OCR success rate (98.2%) | processed / (processed + failed) from real statuses | ADAPT |
| Documents over time (30 days, line chart, 1,248 +12.4%) | `series.documents` (30 days, real daily counts) | NEW-API |
| 30-days dropdown | fixed 30-day window | DROP (no dropdown) |
| Document types donut (Tax Invoice 62% / Delivery Challan 38%) | `documentsByType` | KEEP |
| "OCR confidence" gauge | confidence was removed from the product | ADAPT -> "OCR success rate" gauge from real statuses |
| Recent activity with status badges | `activityFeed` (real audit events, sentences); badge = event category | KEEP |
| Quick actions (Approvals, Users, Documents, Maintenance) | real routes | KEEP |
| Existing "needs attention" (failed docs, orphaned files) | `failedDocuments`, `orphanedFiles` | KEEP (stays, shown as alert chips) |

## Users (`GET /admin/users` extended, `GET /admin/users/{id}` extended)

| Mockup element | Source | Decision |
|---|---|---|
| "Add user" button | no such feature (signup + approval is the flow) | DROP |
| Stat cards Total / Approved / Pending / Rejected | `statusCounts` (new, from count queries) | NEW-API |
| Card sparklines | no per-status history | DROP (cards without sparkline) |
| Search by name or email | new `q` param | NEW-API |
| Chips All / Approved / Pending / Rejected | existing `status` filter (+ "All" = no filter) | KEEP |
| Role dropdown | new `role` param | NEW-API |
| "Filter" button | nothing behind it | DROP |
| Row checkboxes / bulk | no bulk actions exist | DROP |
| Columns user, role, joined, documents, status, actions | `documentCount` per user (new, one aggregate for the page) | NEW-API |
| Approve / Reject buttons, reason modal | existing endpoints + `RejectReasonModal` (reject/revoke with reason) | KEEP |
| "..." row menu | existing actions: View activity, Edit, Make admin/user, Delete, Re-approve, Revoke. Admin-vs-admin restrictions unchanged | KEEP |
| Pagination | existing `totalPages` | KEEP |
| Selected-user panel: avatar, email, status badge, documents, joined | selected row + `documentCount` | KEEP |
| "Last active" | `lastActiveAt` = latest audit event of that user (new) | NEW-API |
| "Email verified" | not tracked | DROP |
| "Review request" box + Approve user / Reject | existing approve/reject (+ reason modal), shown for pending users | KEEP |
| Decision date + reason (already in app) | `decision`, `decidedAt`, `decisionReason` | KEEP (shown in the panel) |

## Maintenance (`GET /admin/system`, new)

| Mockup element | Source | Decision |
|---|---|---|
| "System healthy" pill | DB ping + OCR lock state from `GET /admin/system`; amber/red if not ok | ADAPT (never hardcoded) |
| "Refresh status" | re-calls `GET /admin/system` | KEEP |
| Storage used "68.4 GB of 100 GB", +4.8 GB this month | real stored bytes: document files (GridFS `fs.files`) + workbook files on disk. No real limit is known | ADAPT (used size only, no "of N GB", no monthly delta) |
| Processed documents 4,812 (+12.4%) + sparkline | `documentsByStatus.processed`, `trends`, `series` | ADAPT |
| System uptime 99.98% / 30 days | no history; only process uptime is real | ADAPT ("Server uptime" = time since the API process started) |
| Storage overview donut Documents / Workbooks / Exports / Temporary files | real bytes: document files, workbook files. No exports/temp category | ADAPT (2 segments) |
| Cleanup: Clear temporary files / Archive old exports / Rebuild OCR indexes | none of these exist | DROP |
| Chat files (admin side) | `POST /chat/messages/file`, `GET /chat/files/{id}`: paperclip in the reply box, chip with thumbnail or PDF icon, image thumbnails and PDF cards in messages, image viewer; "Clear chat..." and global delete also delete files and show file counts; files expire after 30 days ("File expired") | ADD |
| Global chat delete | `GlobalChatDeletePanel` in the danger zone: deletes all chat messages after the typed word and the admin's password (5 attempts per hour); the audit log records counts only | ADD |
| Real maintenance actions | Global delete by age and by year+month (`DELETE /admin/purge-range`, `/purge-months`) with the typed phrase + password twice; per-document file purge lives on Documents | KEEP (in the red "Danger zone" card, confirmation unchanged, never one click) |
| Orphaned files | existing page + count | KEEP (link card) |
| Maintenance activity timeline | last 5 real audit events: global nuke, file purge, orphaned-file actions, user delete (`recentMaintenance`) | NEW-API |
| "Delete all data" | = Global delete (age / months). Its strong confirmation stays | KEEP |

## Other admin pages (restyle only, behaviour unchanged)

Documents, Workbooks, Activity (Logs), Orphaned files, user detail, Profile, Login: same shell and components,
same data and actions. Admin-vs-admin rules, reject/revoke reason modal, route guards, logout and Back behaviour
are not touched.
