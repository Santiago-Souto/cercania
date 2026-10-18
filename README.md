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
| Audio transcription | Functional | Groq Whisper with a care-vocabulary prompt. Verified live on Render with a fictional m4a (CIA-20): transcribed and processed in 6.3 s. Returns timestamped segments, stored on the report and used for citation audio times (CIA-18). Provider decided without a comparison; accuracy on real voices not measured |
| `process_report` pipeline (triage + extraction + compare + store) | Functional | `backend/app/process.py`, reached through `app/ingest.py` by WhatsApp and the web app. Verified end to end on Render with the real models (CIA-20): typed and audio reports, ~6–7 s per report with the server warm. Accuracy at scale not measured yet (see Eval) |
| Structured extraction with verbatim quotes | Functional | `backend/app/extract.py`, Groq `openai/gpt-oss-120b` strict structured output by default; any other vendor via `EXTRACT_MODEL=<provider>:<model>` (`backend/app/llm.py`). Every quote checked in code. Live on Render: all mentioned items extracted with verified quotes. About 1 in 10 calls is still rejected twice by Groq's schema check and returns a retryable `needs_retry` |
| Quote verification (code) | Functional | Normalized whole-word substring match; unit-tested (`backend/tests/test_extract.py`) |
| Emergency triage (model decides) | Functional | `backend/app/triage.py`, Groq `openai/gpt-oss-120b` by default (switch with `TRIAGE_MODEL=<provider>:<model>`), runs on every message that reaches `process_report`. Fixed reply text and recipients in code. Live on Render it runs on every report (`status: ok` means the call completed, not that the decision was right). Its accuracy is not measured: an informal local check against Groq (3 messages, 2 of them emergencies) was classified correctly but is not in the repo; eval case c003 covers one emergency. Criteria provisional. Family, doctor and patient messages do not reach it from WhatsApp yet (see Pending) |
| Comparison vs care plan / history / checklist (code) | Functional | `backend/app/compare.py`: omissions, changes, missing checklist items. No model. Live on Render: omission and "Apetito: bajo, 3 turnos seguidos" fired on an unplanned report |
| Confirmation reply to caregiver ("I recorded...") | Functional | Caregiver identified by phone, "which patient?" when several; `confirmation_text` written by code, with the fixed red-flag line on emergencies |
| Report from the web app (text or audio) | Functional | `POST /patients/{id}/reports` runs the same `process_report`; idempotent on `client_id` (a repeat returned the same report). Verified live on Render for text and audio (CIA-20). Web screen `/patients/{id}/reports/new` (CIA-31): record (MediaRecorder) or type, one `client_id` per attempt, shows `confirmation_text`, missing items and alerts, with clear microphone / upload / `needs_retry` / network errors |
| Voice note storage | Functional | `backend/app/storage.py`: the original audio of every stored audio report (web or WhatsApp) goes to a private Supabase Storage bucket after the reply; one object and one `file` row per report. `GET /reports/{id}/audio` returns a 5-minute signed URL. A failed upload never loses the report (`audio_url` stays `null`). Needs `SUPABASE_URL` / `SUPABASE_SERVICE_KEY`; without them nothing is stored |
| Versioned report storage and corrections | Functional | `report_version`; `POST /reports/{id}/corrections` adds a new version, earlier versions stay immutable |
| Read API (patients, reports, alerts, versions) | Functional | `backend/app/api/`; contract in `docs/contract.md` |
| Emergency notifications: web inbox | Functional | `backend/app/notify.py` writes one row per recipient; the web polls `GET /me/notifications` about every 5 s and shows a toast and a browser notification while the tab is open |
| Emergency notifications by WhatsApp | Pending | Code path built, off by default: each attempt is recorded as `skipped` unless `NOTIFY_WHATSAPP=1`. Needs Meta approval (template or recipients on the allowed list) |
| Cited natural-language query | Functional | `POST /patients/{id}/query` (Groq `openai/gpt-oss-120b`, switch with `QUERY_MODEL`); every citation verified in code. Live on Render: cited answer in 3.3 s, citation found verbatim in the transcript; "unclear" when the reports do not say |
| Web timeline (caregiver view) | Pending | Web owner |
| Family read-only view | Pending | Web owner |
| Doctor edits care plan (new version) | Pending | Role and permission in schema; no endpoint/view yet |
| Patient view (how I feel + I need help; no reports or alerts) | In progress | Backend done (CIA-29, `backend/app/patient_messages.py`): "Necesito ayuda" notifies every caregiver and health-team member in the web inbox with no model call; "Cómo me siento" (text or audio) goes through triage and notifies the team only on a red flag. Replies to the patient are fixed text. WhatsApp copies are best effort (`NOTIFY_WHATSAPP`). Screen pending (CIA-35) |
| Login with 6-digit SMS code | Functional | `POST /auth/signup`, `/auth/login`, `/auth/verify`, `/auth/logout` (`backend/app/api/auth.py`), code sent by Twilio SMS, session cookie. Web screens `/login` and `/login/code` (CIA-32): sign-up / login, "terminado en {últimos 4}", resend countdown, a Spanish message per error code, a "código vencido" state, and routing by memberships (a patient goes to their own view, everyone else to My patients); "Salir" in the top bar logs out. The browser calls the API through the web's own `/api/*` proxy (`web/next.config.ts`), so the session cookie is first-party and server-rendered screens forward it. Verified locally against the backend (login, wrong code, 5 wrong codes, resend, sign-up, patient routing, logout). A Twilio trial only texts numbers verified in its console |
| Eval script and 20 cases | In progress | `eval/run_eval.py` built and tested; 4 cases in `eval/cases.csv` (c003 is an emergency), all `dev`, 0 unseen. Scores emergency recall and emergency false alarms on their own lines. Groq's free tier (8,000 tokens/minute) allows only a few reports per minute: run it with `--delay 30` |

### Simulated

- **Caller identity (dev fallback):** the API identifies the caller by the session cookie from `POST /auth/verify`. Once someone logs in on the web, only that cookie is sent. While nobody is logged in, the web app still sends an `X-Person-Id` header: the **Simulado** persona picker in the app shell (Ana `cg_001` caregiver / Carmen `fam_001` family, stored in a cookie) or `NEXT_PUBLIC_DEV_PERSON_ID` (`web/lib/api-shared.ts`); anyone can claim any id, so it is honored only with `ALLOW_DEV_IDENTITY_HEADER=1` (local dev / demo with fictional data). Without it, a visitor who is not logged in is sent to `/login`. Not for real data.
- **Login code on the Twilio trial (demo only):** a trial account only sends predefined templates, so with `TWILIO_TRIAL_TEMPLATE=sms_2fa` the backend sends Twilio's `sms_2fa` template and reads the code from Twilio's reply. A real SMS arrives, but on the trial that code is **always the same**, so anyone who knows it can log in as any registered phone. Only with fictional data; leave it unset once the account is upgraded (then our own random code is sent).
- **Login code delivery (dev only):** with `AUTH_DEV_LOG_CODES=1` the code is written to the API log instead of being texted, for local dev without Twilio. Never set in a real deploy.
- **Fake model clients** exist only in the backend tests. The running app calls the real models.
- Patient, care plan and history data are fictional seed data (`backend/app/seed.py`). Seeded reports are marked `channel="seed"`, `model="seed"`: they are fixtures, not model output.
- Web app screens show contract-shaped fake data (`web/lib/fake.ts`) until the backend endpoints land; a "Datos de prueba ficticios" banner is shown while it is on. With fake data on, sending a new report returns the contract's example result whatever was sent (`fakeProcessResult`). With `NEXT_PUBLIC_USE_FAKE_DATA=0` the web reads the real backend, including the emergency notifications (inbox polled every 5 s, toast, browser Notification). With fake data on, the login screens accept any phone and any 6 digits without calling the backend. Buttons that need the backend (help, invite) are not wired yet.

### Pending

- WhatsApp emergency notifications, pending Meta approval. `NOTIFY_WHATSAPP=0` by default, so they are recorded as `skipped`; the web inbox is the channel in use.
- Audio playback of citations in the web (CIA-13). The backend side is ready: voice notes are stored in a private Supabase Storage bucket (CIA-44), `GET /reports/{id}/audio` returns a 5-minute signed URL, and items and citations carry `audio_start_sec` / `audio_end_sec` (CIA-18). Whisper segments can be long (a 13 s note came back as one segment), so a fragment may cover more than the quote.
- Audio retention: stored voice notes are never deleted yet.
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

Deploy: live URLs, env vars and troubleshooting in [`docs/deploy.md`](docs/deploy.md). `render.yaml` is a Render Blueprint (Render -> New -> Blueprint -> this repo). Health check at `/health`. It creates two services: `cercania-api` (backend) and `cercania-web` (Next.js). On first deploy Render asks for the secrets; set `NEXT_PUBLIC_API_URL` on the web to the API's public URL (`https://cercania-api.onrender.com` or whatever Render assigns). The web ships with `NEXT_PUBLIC_USE_FAKE_DATA=1` (fictional data, banner shown) until the read endpoints land. Free services sleep: open both URLs a minute before a demo.

Database on Supabase:
1. Create a project at supabase.com (free plan). Save the database password.
2. Dashboard -> **Connect** -> copy the **Session pooler** connection string (port 5432, user `postgres.<project-ref>`). Render is IPv4-only and the direct connection is IPv6, so use the pooler.
3. Put it, with the password filled in, in `.env` as `DATABASE_URL` for local use, and in Render as the `DATABASE_URL` secret.
4. `python -m app.seed` creates the tables and fictional data in Supabase. The backend adds `sslmode=require` itself.

Web (Node 20+, Next.js 16 + shadcn/ui, mobile-first):

```bash
cd web
npm install
npm run dev       # fake data, http://localhost:3000 -> /login
npm run dev:real  # real backend at NEXT_PUBLIC_API_URL (proxied as /api/*)
npm run lint && npm run build
```

Fake data is opt-in: only `NEXT_PUBLIC_USE_FAKE_DATA=1` (set by `npm run dev`) shows it. Without it the app calls the backend at `NEXT_PUBLIC_API_URL`, so a deploy never shows fabricated patients by accident. To log in against a local http backend, start it with `AUTH_DEV_LOG_CODES=1 SESSION_COOKIE_SECURE=0 SESSION_COOKIE_SAMESITE=lax` (the code is printed in the API log). Design and screen map: `docs/design/DESIGN.md`.

## Evaluation

```bash
cd backend && source .venv/bin/activate && cd ..
python eval/run_eval.py                 # all cases, seen and unseen reported separately
python eval/run_eval.py --split unseen  # only the held-out cases
python eval/run_eval.py --json out.json # per-case details
```

Runs every case in `eval/cases.csv` through the real `process_report` on a fresh temporary SQLite database with the fictional seed data (the team database is never touched). Needs the API keys of the configured providers: by default only `GROQ_API_KEY` (extraction and triage); `LLM_API_KEY` (+ `LLM_BASE_URL`) for any `openai:<model>`.

Reports: fields extracted (value + verified quote), omissions detected, changes detected, emergencies detected (and emergency false alarms, reported on their own line), missing checklist items detected, false alarms (unexpected alerts, items reported but not mentioned, items flagged missing but mentioned), quote-verification pass rate, and latency per report. Change alerts are expected as `change:<item>` in `expected_alerts`. A case where `process_report` raises or returns a status other than `ok` counts as failed: its expected counts stay in every ratio with zero detections, and the run exits with code 1. The wording of extracted values is not judged. Cases with `split=unseen` are held out from prompt tuning (keep at least 5).
