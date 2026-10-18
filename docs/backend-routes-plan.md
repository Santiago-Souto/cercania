# Backend routes + notifications plan (Oct 17)

Goal: the demo flow works end to end from the **web app**, with no dependency on WhatsApp being approved by Meta.

> Caregiver (Ana, `cg_001`) is with Rosa (`pat_001`). Rosa falls. Ana records/types a report in the web app
> -> `POST /patients/pat_001/reports` -> triage says emergency, extraction records the checklist
> -> report stored with `red_flag` + `emergency` alert (+ omission / missing-item alerts)
> -> Ana sees the fixed emergency message
> -> family (Carmen, `fam_001`) gets a **web notification** (inbox polled every ~5 s, shown as a toast and a
>    browser `Notification` while the tab is open) and, best effort, a WhatsApp message
> -> family opens the alert, sees the report with verified quotes.

## Decisions

- **Notifications are channel-agnostic.** Every recipient gets a row in a new `notification` table per channel.
  `web` is the primary channel today (in-app inbox, polled). `whatsapp` is attempted only when
  `NOTIFY_WHATSAPP=1`; otherwise it is recorded as `skipped`. Failures are recorded and shown, never silent.
- **No Web Push (VAPID / service worker).** Out of scope (AGENTS.md §10). Polling + the browser `Notification`
  API gives the same demo effect while the tab is open, with nothing to install.
- **Emergency reply first, notifications after**, in the background (AGENTS.md §4.2). `process_report` stores
  the alert; the channel calls `notify.dispatch_emergency(report_id)` after replying. Dispatch is idempotent.
- **Recipients come from code** (`models.emergency_recipients`): health provider, caregivers, family; never the
  patient, the doctor role, or the sender.
- **Structure**: new routes live in an `app/api/` package; shared `errors.py`, `schemas.py` (Pydantic response
  models, so `/docs` documents the contract), `serializers.py` (ORM -> contract dicts, one place).
  `whatsapp.py` and `web_reports.py` stay where they are to avoid conflicts with the other devs.
- **Frontend compatibility (PR #3)**: report JSON keeps the contract fields (`kind`, `sender`, `triage`) and also
  carries `caregiver` (= sender) and `red_flag_quote` (= triage quote), which `web/lib/types.ts` reads.
  Alerts gain an `id`. All additive.
- **Auth stays SIMULATED** (`X-Person-Id` with `ALLOW_DEV_IDENTITY_HEADER=1`) until CIA-26/32. CORS allows the
  web origin(s) in `WEB_ORIGINS` with credentials and the `X-Person-Id` header.
- **`process_report` (CIA-7)** is built in its own commit (`app/process.py`, `app/compare.py`) so it can be
  dropped if the brain owner's version lands first.

## Layout

```
backend/app/
  errors.py          api_error(), exception handlers ({error:{code,message}})
  schemas.py         Pydantic response/request models for every endpoint below
  serializers.py     report/item/alert/patient/notification -> contract dicts; process_result(report)
  deps.py            get_db, current_person_id, patient_access(permission) dependency
  process.py         process_report: triage || extraction -> compare -> store -> ProcessResult
  compare.py         missing items, omissions vs plan, changes vs history (no model)
  notify.py          dispatch_emergency(report_id): web inbox rows + WhatsApp attempts, logged on the alert
  query.py           cited natural-language answers (Sonnet), quotes verified in code
  api/__init__.py    api_router (includes every router below)
  api/patients.py    GET /patients/{id}, /patients/{id}/reports, /patients/{id}/alerts
  api/reports.py     GET /reports/{id}, /reports/{id}/versions
  api/corrections.py POST /reports/{id}/corrections
  api/me.py          GET /me, /me/patients
  api/notifications.py GET /me/notifications, POST /me/notifications/{id}/read, POST /me/notifications/read-all
  api/query.py       POST /patients/{id}/query
```

## Endpoints

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/patients/{id}` | `read_care_plan` | Contract shape, active plan |
| GET | `/patients/{id}/reports?limit=20&before=<iso>` | `read_reports` | Newest first, latest version of each, `next_before` |
| GET | `/patients/{id}/alerts?since=<iso>&limit=50` | `read_reports` | Alerts on each report's latest version, newest first, with `report_id` |
| GET | `/reports/{id}` | `read_reports` on its patient | One report, latest version |
| GET | `/reports/{id}/versions` | `read_reports` | Oldest first |
| POST | `/reports/{id}/corrections` | `correct_report` | New version; author = caller |
| POST | `/patients/{id}/reports` | `send_report` | Exists (`web_reports.py`); now schedules `dispatch_emergency` |
| POST | `/patients/{id}/query` | `read_reports` | Cited answer |
| GET | `/me` | any | Person + memberships (role per patient) |
| GET | `/me/patients` | any | `MyPatient[]` as in `web/lib/types.ts` |
| GET | `/me/notifications?since=<iso>&unread_only=1` | any | Web inbox, newest first, `unread_count` |
| POST | `/me/notifications/{id}/read` | owner | Marks read |
| POST | `/me/notifications/read-all` | any | Marks all read |

Not built (declare as Pending): members/invites, patient messages, team messages, real auth.

## Notification model

`notification`: `id` (`ntf_…`), `alert_id`, `report_id`, `patient_id`, `person_id` (null for the health provider),
`recipient` (`health_provider|caregiver|family`), `channel` (`web|whatsapp`), `status`
(`sent|failed|skipped`), `error`, `title`, `body`, `created_at`, `read_at`.
`alert.notifications` (contract) keeps a summary list: `{to, person_id, channel, status, error}`.

## Work split (subagents)

1. Foundation (sequential): errors, schemas, serializers, deps, `Notification` model, `api/` stubs, main.py
   (lifespan `init_db`, CORS, router, validation-error handler).
2. In parallel, each in its own files:
   - Read routes: `api/patients.py`, `api/reports.py`, `api/me.py`.
   - Brain: `process.py`, `compare.py`, `api/corrections.py`.
   - Notifications: `notify.py`, `api/notifications.py`, WhatsApp send result + template fallback in `whatsapp.py`,
     dispatch wiring in `whatsapp.py` and `web_reports.py`.
   - Query: `query.py`, `api/query.py`.
3. Docs (Haiku): `docs/contract.md`, AGENTS.md §9, README Functional/Simulated/Pending.
4. Integration: merge, full test suite, scripted demo run against seed data.

## Frontend follow-ups (web owner)

- Send `X-Person-Id` while auth is simulated; a persona picker for the demo (Ana / Carmen).
- Poll `GET /me/notifications?since=` every 5 s; show a toast + `new Notification(...)` (after permission);
  link to `/patients/{id}/alerts`.
- Read `kind`, `sender`, `triage`, alert `type: "emergency"` and its `notifications` statuses.
