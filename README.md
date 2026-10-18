# CercanIA - care handoff assistant (Build 101)

Caregivers send an end-of-shift report (a voice note or text) from the web app. The system transcribes it, extracts structured data with a verbatim quote per fact, compares it against the patient's care plan and history **in code**, flags omissions and changes, and stores a versioned record. The next shift can ask questions in natural language and gets answers citing the original fragment.

> Not a medical product. It does not diagnose and does not suggest doses. All demo data is fictional.

See `AGENTS.md` for full project context and rules, and `docs/contract.md` for interfaces.

## How the AI is central

Without the AI there is no transcription of free-form speech, no extraction of structured facts from messy language, and no cited natural-language querying. The model reads and explains; code calculates, compares and verifies (every quote is checked against the transcript). The one decision left to the model is emergency triage; the reply text and who gets notified stay in code.

## Status

Update this table as work lands. Mark anything mocked as **Simulated**. Be honest: reviewers read this first.

| Capability | Status | Notes |
|---|---|---|
| Audio transcription | Functional | Groq Whisper with a care-vocabulary prompt. Verified live on Render with a fictional m4a (CIA-20): transcribed and processed in 6.3 s. Returns timestamped segments, stored on the report and used for citation audio times (CIA-18). Provider decided without a comparison; accuracy on real voices not measured |
| `process_report` pipeline (triage + extraction + compare + store) | Functional | `backend/app/process.py`, reached through `app/ingest.py` by the web app. Verified end to end on Render with the real models (CIA-20): typed and audio reports, ~6–7 s per report with the server warm. Eval on 20 fictional cases: see the Eval row |
| Structured extraction with verbatim quotes | Functional | `backend/app/extract.py`, Groq `openai/gpt-oss-120b` strict structured output by default; any other vendor via `EXTRACT_MODEL=<provider>:<model>` (`backend/app/llm.py`). Every quote checked in code. Live on Render: all mentioned items extracted with verified quotes. About 1 in 10 calls is still rejected twice by Groq's schema check and returns a retryable `needs_retry` |
| Quote verification (code) | Functional | Normalized whole-word substring match; unit-tested (`backend/tests/test_extract.py`) |
| Emergency triage (model decides) | Functional | `backend/app/triage.py`, Groq `openai/gpt-oss-120b` by default (switch with `TRIAGE_MODEL=<provider>:<model>`), runs on every message that reaches `process_report`. Fixed reply text and recipients in code. Live on Render it runs on every report (`status: ok` means the call completed, not that the decision was right). Eval (20 fictional cases, single run): 4/4 emergencies detected and 0 false emergencies, including 5 look-alikes such as "sin caídas" or a fall already handled (`eval/RESULTS.md`). Criteria provisional. Family and doctor emergencies have no input yet: only caregivers send reports and the patient uses the patient view (see Pending) |
| Comparison vs care plan / history / checklist (code) | Functional | `backend/app/compare.py`: omissions, changes, missing checklist items. No model. Live on Render: omission and "Apetito: bajo, 3 turnos seguidos" fired on an unplanned report |
| Confirmation to caregiver ("I recorded...") | Functional | Patient from the URL; `confirmation_text` written by code, with the fixed red-flag line on emergencies |
| Report from the web app (text or audio) | Functional | `POST /patients/{id}/reports` runs the same `process_report`; idempotent on `client_id` (a repeat returned the same report). Verified live on Render for text and audio (CIA-20). Web screen `/patients/{id}/reports/new` (CIA-31): record (MediaRecorder) or type, one `client_id` per attempt, shows `confirmation_text`, missing items and alerts, with clear microphone / upload / `needs_retry` / network errors |
| Audio playback of citations | Functional | Web (CIA-13, `web/components/app/audio-player.tsx`): tapping a citation in Preguntar, or a quote on a report, plays exactly that fragment of the original voice note; "Escuchar nota de voz" plays the whole note. Signed URL from `GET /reports/{id}/audio` (CIA-44), times from Groq's word timestamps. Verified in headless Chromium against the Render API. Reports stored before word timestamps play their whole note |
| Voice note storage | Functional | `backend/app/storage.py`: the original audio of every stored audio report goes to a private Supabase Storage bucket after the reply; one object and one `file` row per report. `GET /reports/{id}/audio` returns a 5-minute signed URL. A failed upload never loses the report (`audio_url` stays `null`). Needs `SUPABASE_URL` / `SUPABASE_SERVICE_KEY`; without them nothing is stored |
| Versioned report storage and corrections | Functional | `report_version`; `POST /reports/{id}/corrections` adds a new version, earlier versions stay immutable |
| Read API (patients, reports, alerts, versions) | Functional | `backend/app/api/`; contract in `docs/contract.md` |
| Emergency notifications: web inbox (the only channel) | Functional | `backend/app/notify.py` writes one row per caregiver and family member (not the sender, not the patient); the web polls `GET /me/notifications` about every 5 s and shows a toast and a browser notification while the tab is open |
| Cited natural-language query | Functional | `POST /patients/{id}/query` (Groq `openai/gpt-oss-120b`, switch with `QUERY_MODEL`); every citation verified in code. Live on Render: cited answer in 3.3 s, citation found verbatim in the transcript; "unclear" when the reports do not say |
| Web timeline (caregiver view) | Functional | Patient home, report detail with versions, alerts and cited query, all from the backend |
| Family read-only view | Functional | Screen reads the backend; family writes to the health team from `/patients/{id}/messages` (CIA-36) |
| Admin: users and roles | Functional | CIA-48. A global admin (`person.is_admin`, set by hand in the database, from an `admin` pre-registration, or by another admin with confirmation) lists people and assigns roles, nothing else: no reports, alerts, care plans or messages. Pre-registers phones that have not signed up (phone + role + patient; caregivers and admins may go without a patient): the person signs up on their own and starts with that role. A change that would replace something answers `409` with the current state and needs confirmation; every change is logged in `role_change`. **Self sign-up is always patient** (own profile); family and invited patients come from a caregiver's invite. API `backend/app/api/admin.py`, rules `backend/app/roles.py`, web `/admin`. Seed admin: `adm_001` (fictional) |
| Add patient, care plan and team invites | Functional | `POST /patients` (caregivers only; creator becomes caregiver, care plan v1, doses stored as typed), `GET /patients/{id}/members`, `POST /patients/{id}/invites` and `POST /invites` (caregivers only, **family or patient**, phone number only; becomes a membership when that phone accepts it in the app; a patient invite without a patient creates the person's profile with the caregiver attached). Web: role picker on the invite form, and "Invitar a un paciente" (`/patients/invite`). Web: `/patients/new` and `/patients/{id}/team` (CIA-34) |
| Patient emergency number + call button | Functional | `emergency_contact` on `GET`/`POST /patients`, `PATCH /patients/{id}/emergency-contact` (caregiver and doctor only, CIA-51). Web: optional field on `/patients/new`, card with "Editar" on the patient page, and a `tel:` button (the contact's name, or "Llamar al 911") on the red-flag result, the patient banner, and the alerts and family screens. Nothing is called or sent automatically. Verified by backend tests; the call itself was not exercised on a phone |
| Doctor edits care plan (new version) | Pending | Role and permission in schema; no endpoint/view yet |
| Patient view (how I feel + I need help; no reports or alerts) | Functional | Backend done (CIA-29, `backend/app/patient_messages.py`): "Necesito ayuda" notifies every caregiver and health-team member in the web inbox with no model call; "Cómo me siento" (text or audio) goes through triage and notifies the team only on a red flag. Replies to the patient are fixed text. Screen `/patients/[id]/me` (CIA-35): voice (same recorder as the new report screen), text, "Necesito ayuda" with one confirmation, the backend's fixed reply, and the patient's own messages with who saw them. A patient is sent to this screen from the list and the patient home; the backend answers 403 to reports, alerts and query |
| Family <-> health team messages | Functional | `GET`/`POST /patients/{id}/messages` (`backend/app/api/messages.py`, CIA-36): one thread per patient, family and health team only (caregiver and patient get 403). Human to human, no model call. Screen `/patients/{id}/messages`: sends optimistically (sending / failed with retry), polls every 5 s, shows read state on your own messages; always shows "No es para urgencias". No notification is sent for a new message: the other side sees it when they open the thread |
| Login with 6-digit SMS code | Functional | `POST /auth/signup`, `/auth/login`, `/auth/verify`, `/auth/logout` (`backend/app/api/auth.py`), code sent by Twilio SMS, session cookie. Web screens `/login` and `/login/code` (CIA-32): sign-up / login tabs, 6-digit input with paste and `one-time-code` autofill, resend countdown, a Spanish message per error, "código vencido" state, then a lone `patient` membership opens the patient view and everyone else "Mis pacientes". The session lasts `SESSION_TTL_DAYS` (30 by default) on that device: opening the app again skips the login until it expires or the person taps "Salir". Verified locally end to end against the seed data. A Twilio trial only texts numbers verified in its console |
| Web reads the real API (no fake data) | Functional | CIA-14: every screen reads the backend as the logged-in person. Server components forward the session cookie; browser calls go through the same-origin `/api` rewrite (`web/next.config.ts`) so the cookie is first-party on Render. No session or a `401` sends the person to `/login` |
| Eval script and 20 cases | Functional | `eval/run_eval.py` on 20 fictional text cases (`eval/cases.csv`: 14 `dev`, 6 `unseen`; 4 emergencies, 5 look-alikes, planted omissions and missing items), database reset per case. First run with the real models (Groq `openai/gpt-oss-120b`), all 20 / unseen 6: fields extracted 98% / 97%, omissions 100% / 100%, changes 83% / 80%, emergencies 4/4 / 1/1 with 0 false emergencies, missing items 100%, quote verification 99% / 97%, 2 false alarms (both in `dev`), median latency 3.9 s. Details and misses in `eval/RESULTS.md`. Single run; the model is not deterministic. CIA-52 added 6 unseen cases (c021-c026: 3 emergencies, 3 look-alikes; 26 cases, 12 unseen, 4 unseen emergencies) that **have not been run yet** (pending a `GROQ_API_KEY`); the numbers above are for the original 20. Not measured yet: the cited query, and audio versions of the cases. Run with `--delay 30` (Groq free tier: 8,000 tokens/minute) |

### Simulated

- **Caller identity (backend dev fallback):** the API identifies the caller by the session cookie from `POST /auth/verify`, and the web app only uses that. For curl and backend tests, `ALLOW_DEV_IDENTITY_HEADER=1` also accepts an `X-Person-Id` header when there is no cookie (`backend/app/deps.py`); anyone can claim any id that way, so it stays unset in the deploy.
- **Login code on the Twilio trial (demo only):** a trial account only sends predefined templates, so with `TWILIO_TRIAL_TEMPLATE=sms_2fa` the backend sends Twilio's `sms_2fa` template and reads the code from Twilio's reply. A real SMS arrives, but on the trial that code is **always the same**, so anyone who knows it can log in as any registered phone. Only with fictional data; leave it unset once the account is upgraded (then our own random code is sent).
- **Login code delivery (dev only):** with `AUTH_DEV_LOG_CODES=1` the code is written to the API log instead of being texted, for local dev without Twilio. Never set in a real deploy.
- **Fake model clients** exist only in the backend tests. The running app calls the real models.
- Patient, care plan and history data are fictional seed data (`backend/app/seed.py`). Seeded reports are marked `channel="seed"`, `model="seed"`: they are fixtures, not model output.

### Pending

- Notifications outside the app: emergencies and help requests reach people only through the web inbox, so someone who never opens the app is not reached. The patient's emergency number (editable by caregiver and doctor) is only offered as a call button in the web (911 when none is set); the server never calls or texts it.
- Audio retention: stored voice notes are never deleted yet.
- Eval of the cited query (`POST /patients/{id}/query`): only `process_report` is measured so far. Audio recordings of the eval cases by team voices.

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

Deploy: live URLs, env vars and troubleshooting in [`docs/deploy.md`](docs/deploy.md). `render.yaml` is a Render Blueprint (Render -> New -> Blueprint -> this repo). Health check at `/health`. It creates two services: `cercania-api` (backend) and `cercania-web` (Next.js). On first deploy Render asks for the secrets; set `NEXT_PUBLIC_API_URL` on the web to the API's public URL (`https://cercania-api.onrender.com` or whatever Render assigns). Free services sleep: open both URLs a minute before a demo.

Database on Supabase:
1. Create a project at supabase.com (free plan). Save the database password.
2. Dashboard -> **Connect** -> copy the **Session pooler** connection string (port 5432, user `postgres.<project-ref>`). Render is IPv4-only and the direct connection is IPv6, so use the pooler.
3. Put it, with the password filled in, in `.env` as `DATABASE_URL` for local use, and in Render as the `DATABASE_URL` secret.
4. `python -m app.seed` creates the tables and fictional data in Supabase. The backend adds `sslmode=require` itself.

Web (Node 20+, Next.js 16 + shadcn/ui, mobile-first):

```bash
cd web
npm install
npm run dev       # http://localhost:3000 -> /login, backend at NEXT_PUBLIC_API_URL (web/.env.local)
npm run lint && npm run build
```

The web always reads the backend; there is no fake data. Log in with a seeded fictional phone (`backend/app/seed.py`, e.g. Ana `+15550100001`). Without Twilio, run the backend with `AUTH_DEV_LOG_CODES=1` (the code is printed in the API log) and, on http, `SESSION_COOKIE_SECURE=0`. Design and screen map: `docs/design/DESIGN.md`.

## Evaluation

```bash
cd backend && source .venv/bin/activate && cd ..
python eval/run_eval.py                 # all cases, seen and unseen reported separately
python eval/run_eval.py --split unseen  # only the held-out cases
python eval/run_eval.py --json out.json # per-case details
```

Runs every case in `eval/cases.csv` through the real `process_report` on a fresh temporary SQLite database with the fictional seed data (the team database is never touched). Needs the API keys of the configured providers: by default only `GROQ_API_KEY` (extraction and triage); `LLM_API_KEY` (+ `LLM_BASE_URL`) for any `openai:<model>`.

Reports: fields extracted (value + verified quote), omissions detected, changes detected, emergencies detected (and emergency false alarms, reported on their own line), missing checklist items detected, false alarms (unexpected alerts, items reported but not mentioned, items flagged missing but mentioned), quote-verification pass rate, and latency per report. Change alerts are expected as `change:<item>` in `expected_alerts`. A case where `process_report` raises or returns a status other than `ok` counts as failed: its expected counts stay in every ratio with zero detections, and the run exits with code 1. The wording of extracted values is not judged. Cases with `split=unseen` are held out from prompt tuning (keep at least 5).
