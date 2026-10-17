# CercanIA - care handoff assistant (Build 101)

Caregivers send an end-of-shift voice note to a WhatsApp bot. The system transcribes it, extracts structured data with a verbatim quote per fact, compares it against the patient's care plan and history **in code**, flags omissions and changes, and stores a versioned record. The next shift can ask questions in natural language and gets answers citing the original fragment.

> Not a medical product. It does not diagnose and does not suggest doses. All demo data is fictional.

See `AGENTS.md` for full project context and rules, and `docs/contract.md` for interfaces.

## How the AI is central

Without the AI there is no transcription of free-form speech, no extraction of structured facts from messy language, and no cited natural-language querying. The model reads and explains; code calculates, compares and verifies (every quote is checked against the transcript). The one decision left to the model is emergency triage; the reply text and who gets notified stay in code.

## Status

Update this table as work lands. Mark anything mocked as **Simulated**. Be honest: reviewers read this first.

| Capability | Status | Notes |
|---|---|---|
| Voice note received from WhatsApp | In progress | Meta Cloud API, bot number +1 555-674-0716 (test number: only allowed phones can write). Inbound voice notes verified against a real Meta payload; end-to-end with transcription pending the Groq key |
| Audio transcription | In progress | Groq Whisper with a care-vocabulary prompt; live test pending |
| `process_report` pipeline (triage + extraction + compare + store) | Functional | `backend/app/process.py`, reached through `app/ingest.py` by WhatsApp and the web app. Unit-tested with fake model clients; not yet run against the real models (see Eval) |
| Structured extraction with verbatim quotes | Functional | `backend/app/extract.py`, Claude Haiku 5.5 structured output; every quote checked in code. Live accuracy not measured yet |
| Quote verification (code) | Functional | Normalized whole-word substring match; unit-tested (`backend/tests/test_extract.py`) |
| Emergency triage (model decides) | Functional | `backend/app/triage.py`, Claude Haiku 5.5, runs on every message that reaches `process_report`. Fixed reply text and recipients in code. Criteria provisional; live accuracy not measured yet. Family, doctor and patient messages do not reach it from WhatsApp yet (see Pending) |
| Comparison vs care plan / history / checklist (code) | Functional | `backend/app/compare.py`: omissions, changes, missing checklist items. No model |
| Confirmation reply to caregiver ("I recorded...") | Functional | Caregiver identified by phone, "which patient?" when several; `confirmation_text` written by code, with the fixed red-flag line on emergencies |
| Report from the web app (text) | Functional | `POST /patients/{id}/reports` runs the same `process_report`; idempotent on `client_id`. Audio path needs the Groq key |
| Versioned report storage and corrections | Functional | `report_version`; `POST /reports/{id}/corrections` adds a new version, earlier versions stay immutable |
| Read API (patients, reports, alerts, versions) | Functional | `backend/app/api/`; contract in `docs/contract.md` |
| Emergency notifications: web inbox | Functional | `backend/app/notify.py` writes one row per recipient; the web polls `GET /me/notifications` about every 5 s and shows a toast and a browser notification while the tab is open |
| Emergency notifications by WhatsApp | Pending | Code path built, off by default: each attempt is recorded as `skipped` unless `NOTIFY_WHATSAPP=1`. Needs Meta approval (template or recipients on the allowed list) |
| Cited natural-language query | Functional | `POST /patients/{id}/query` (Sonnet); every citation verified in code. Not yet evaluated against the real model |
| Web timeline (caregiver view) | Pending | Web owner |
| Family read-only view | Pending | Web owner |
| Doctor edits care plan (new version) | Pending | Role and permission in schema; no endpoint/view yet |
| Patient view (own care plan, no reports) | Pending | Role and permission in schema; no endpoint/view yet |
| Single-use magic-link access | Pending | No `/auth/link` route yet |
| Eval script and 20 cases | In progress | `eval/run_eval.py` built and tested; 2 cases so far, 0 unseen. The run against the real `process_report` and query is still to do |

### Simulated

- **Caller identity:** until the login backend lands, the web app identifies the user with an `X-Person-Id` header (`backend/app/deps.py`). Anyone can claim any id, so it is honored only with `ALLOW_DEV_IDENTITY_HEADER=1` (local dev / demo with fictional data); otherwise every call gets 401. Not for real data.
- **Fake model clients** exist only in the backend tests. The running app calls the real models.
- Patient, care plan and history data are fictional seed data (`backend/app/seed.py`). Seeded reports are marked `channel="seed"`, `model="seed"`: they are fixtures, not model output.
- **Audio:** no audio file is stored yet. `audio_url` is a placeholder path (`/media/{id}`) with no route behind it.

### Pending

- Real auth (CIA-26/32). Magic-link login is not built.
- WhatsApp emergency notifications, pending Meta approval. `NOTIFY_WHATSAPP=0` by default, so they are recorded as `skipped`; the web inbox is the channel in use.
- Audio storage and `audio_url` (Supabase Storage, signed URLs).
- Transcript segments: citations have no audio times yet (`audio_start_sec` / `audio_end_sec` are `null`).
- Members, invites and messages endpoints.
- Eval not yet run against the real model for `process_report` and the cited query.

### Out of scope (declared)

- Integration with health-system or clinical records.
- Web Push (service worker / VAPID) and complex auth. The polled inbox and the browser Notification API are the interim channel.
- Agent voice replies.

## Run locally

Backend (Python 3.12+):

```bash
cp .env.example .env            # default DATABASE_URL is local SQLite
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m app.seed              # tables + fictional data (--reset drops all tables)
# No migrations yet: after a schema change (e.g. report.sender_id, triage fields),
# run `python -m app.seed --reset`. It drops everything; all data is fictional.
uvicorn app.main:app --reload   # http://localhost:8000/health
pytest                          # backend tests
```

Deploy: `render.yaml` is a Render Blueprint (Render -> New -> Blueprint -> this repo). Health check at `/health`.

Database on Supabase:
1. Create a project at supabase.com (free plan). Save the database password.
2. Dashboard -> **Connect** -> copy the **Session pooler** connection string (port 5432, user `postgres.<project-ref>`). Render is IPv4-only and the direct connection is IPv6, so use the pooler.
3. Put it, with the password filled in, in `.env` as `DATABASE_URL` for local use, and in Render as the `DATABASE_URL` secret.
4. `python -m app.seed` creates the tables and fictional data in Supabase. The backend adds `sslmode=require` itself.

Web: run commands go here once `web/` is scaffolded.

## Evaluation

```bash
cd backend && source .venv/bin/activate && cd ..
python eval/run_eval.py                 # all cases, seen and unseen reported separately
python eval/run_eval.py --split unseen  # only the held-out cases
python eval/run_eval.py --json out.json # per-case details
```

Runs every case in `eval/cases.csv` through the real `process_report` on a fresh temporary SQLite database with the fictional seed data (the team database is never touched). Needs `ANTHROPIC_API_KEY`.

Reports: fields extracted (value + verified quote), omissions detected, missing checklist items detected, false alarms (unexpected alerts, items reported but not mentioned, items flagged missing but mentioned), quote-verification pass rate, and latency per report. Change alerts are expected as `change:<item>` in `expected_alerts`. A case where `process_report` raises or returns a status other than `ok` counts as failed: its expected counts stay in every ratio with zero detections, and the run exits with code 1. The wording of extracted values is not judged. Cases with `split=unseen` are held out from prompt tuning (keep at least 5).
