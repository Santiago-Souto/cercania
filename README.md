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
| Cited natural-language query | Pending | |
| Single-use magic-link access | Pending | |
| Eval script and 20 cases | Pending | |

### Simulated

- Patient, care plan and history data are fictional seed data (`backend/app/seed.py`).

### Out of scope (declared)

- Integration with health-system or clinical records.
- Push notifications, complex auth, agent voice replies.

## Run locally

Backend (Python 3.12+):

```bash
cp .env.example .env
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload   # http://localhost:8000/health
pytest                          # backend tests
```

Deploy: `render.yaml` is a Render Blueprint (Render -> New -> Blueprint -> this repo). Health check at `/health`.

Web: run commands go here once `web/` is scaffolded.

## Evaluation

```bash
# python eval/run_eval.py
```

Reports: fields extracted correctly, omissions detected, missing checklist items detected, false alarms, quote-verification pass rate.
