# CercanIA - care handoff assistant (Build 101)

Caregivers send an end-of-shift voice note to a WhatsApp bot. The system transcribes it, extracts structured data with a verbatim quote per fact, compares it against the patient's care plan and history **in code**, flags omissions and changes, and stores a versioned record. The next shift can ask questions in natural language and gets answers citing the original fragment.

> Not a medical product. It does not diagnose and does not suggest doses. All demo data is fictional.

See `AGENTS.md` for full project context and rules, and `docs/contract.md` for interfaces.

## How the AI is central

Without the AI there is no transcription of free-form speech, no extraction of structured facts from messy language, and no cited natural-language querying. The model reads and explains; code calculates, compares and verifies (every quote is checked against the transcript).

## Status

Update this table as work lands. Mark anything mocked as **Simulated**. Be honest: reviewers read this first.

| Capability | Status | Notes |
|---|---|---|
| Voice note received from WhatsApp | In progress | Meta Cloud API, bot number +1 555-674-0716 (test number: only allowed phones can write). Inbound voice notes verified against a real Meta payload; end-to-end with transcription pending the Groq key |
| Audio transcription | In progress | Groq Whisper with a care-vocabulary prompt; live test pending |
| Structured extraction with verbatim quotes | Pending | |
| Quote verification (code) | Pending | |
| Comparison vs care plan / history / checklist (code) | Pending | |
| Confirmation reply to caregiver ("I recorded...") | In progress | Caregiver identified by phone, "which patient?" when several, `confirmation_text` reply with fixed red-flag line; waits on `process_report` (CIA-7) |
| Report from the web app (text or audio) | In progress | `POST /patients/{id}/reports` built and tested; returns `processing_unavailable` until `process_report` (CIA-7) merges |
| Versioned report storage | Pending | |
| Web timeline (caregiver view) | Pending | |
| Family read-only view | Pending | |
| Doctor edits care plan (new version) | Pending | Role and permission in schema; no endpoint/view yet |
| Patient view (own care plan, no reports) | Pending | Role and permission in schema; no endpoint/view yet |
| Cited natural-language query | Pending | |
| Single-use magic-link access | Pending | |
| Eval script and 20 cases | Pending | |

### Simulated

- **Caller identity:** until the login backend lands, the web app identifies the user with an `X-Person-Id` header (`backend/app/deps.py`). Anyone can claim any id, so it is honored only with `ALLOW_DEV_IDENTITY_HEADER=1` (local dev / demo with fictional data); otherwise every call gets 401. Not for real data.
- Patient, care plan and history data are fictional seed data (`backend/app/seed.py`). Seeded reports are marked `channel="seed"`, `model="seed"`: they are fixtures, not model output.

### Out of scope (declared)

- Integration with health-system or clinical records.
- Push notifications, complex auth, agent voice replies.

## Run locally

Backend (Python 3.12+):

```bash
cp .env.example .env            # default DATABASE_URL is local SQLite
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m app.seed              # tables + fictional data (--reset drops all tables)
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
# python eval/run_eval.py
```

Reports: fields extracted correctly, omissions detected, missing checklist items detected, false alarms, quote-verification pass rate.
