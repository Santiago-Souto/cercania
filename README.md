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
| Voice note received from WhatsApp | Pending | Fallback: Telegram bot or web recorder |
| Audio transcription | Pending | |
| Structured extraction with verbatim quotes | Pending | |
| Quote verification (code) | Pending | |
| Comparison vs care plan / history / checklist (code) | Pending | |
| Confirmation reply to caregiver ("I recorded...") | Pending | |
| Versioned report storage | Pending | |
| Web timeline (caregiver view) | Pending | |
| Family read-only view | Pending | |
| Doctor edits care plan (new version) | Pending | Role and permission in schema; no endpoint/view yet |
| Patient view (own care plan, no reports) | Pending | Role and permission in schema; no endpoint/view yet |
| Cited natural-language query | Pending | |
| Single-use magic-link access | Pending | |
| Eval script and 20 cases | In progress | `eval/run_eval.py` built and tested; needs `process_report` (CIA-7) to run and the 20 cases (CIA-24); 2 cases so far, 0 unseen |

### Simulated

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
cd backend && source .venv/bin/activate && cd ..
python eval/run_eval.py                 # all cases, seen and unseen reported separately
python eval/run_eval.py --split unseen  # only the held-out cases
python eval/run_eval.py --json out.json # per-case details
```

Runs every case in `eval/cases.csv` through the real `process_report` on a fresh temporary SQLite database with the fictional seed data (the team database is never touched). Needs `ANTHROPIC_API_KEY`.

Reports: fields extracted (value + verified quote), omissions detected, missing checklist items detected, false alarms (unexpected alerts, items reported but not mentioned, items flagged missing but mentioned), quote-verification pass rate, and latency per report. The wording of extracted values is not judged. Cases with `split=unseen` are held out from prompt tuning (keep at least 5).
