# Task split (Sat Oct 17)

Three devs working in parallel, following the owners in `AGENTS.md` section 9. Times match `AGENTS.md` section 14. Each dev stays in their own files to avoid merge conflicts. Commit small and often; pull before you push.

## Everyone together (until ~12:30, about 30 min)

- Confirm the stack in `AGENTS.md` section 8: FastAPI, SQLite to start, Next.js or Vite React, Groq or OpenAI Whisper, Claude.
- Agree on `docs/contract.md` and freeze it. After that, change it only in the same commit as the code that needs the change.
- Backend scaffold, `.env.example`, `models.py` and `seed.py` with 3 fictional patients. One person writes them, the other two review.

## Dev A: Brain (backend logic and the AI)

Files: `backend/app/extract.py`, `compare.py`, `query.py`, `models.py`, `seed.py`, `backend/tests/`

| By | Task |
|---|---|
| 12:30 | `models.py` schema with versioned reports; `seed.py` with 3 patients and several days of history so `change` alerts can fire |
| 14:00 | `extract.py`: Claude structured output, one verbatim quote per item, `null` when not mentioned. Quote verification in code (normalized substring match) |
| 15:30 | `compare.py` (no model calls): missing checklist items, omissions vs medication times, changes vs history. Red-flag phrase list in code |
| 16:30 | `process_report()` that runs everything and returns `ProcessResult` exactly as in the contract, idempotent on `message_id`, plus `confirmation_text` |
| 17:00 | **Integration with B and C** |
| 19:30 | `query.py`: answers with verified citations, `unclear` when the records don't say. Corrections create a new version |

## Dev B: Web

Files: `web/`

| By | Task |
|---|---|
| 12:30 | Scaffold, hello world deployed, fake JSON copied exactly from `docs/contract.md` |
| 14:00 | Caregiver view: patient profile with care plan, timeline of reports, each item shows its quote and verified status |
| 15:30 | Alerts panel (omission, change, missing item), red-flag banner, read-only family view |
| 16:30 | Query screen with the answer and its citations; audio player that seeks to `audio_start_sec` |
| 17:00 | **Swap fake data for the real API** |
| 19:30 | Magic-link landing page (reads the token, picks the role), clear loading and error states, text-input fallback for the demo |

## Dev C: Infra and input

Files: `backend/app/main.py`, `whatsapp.py`, `transcribe.py`, `eval/`

| By | Task |
|---|---|
| 12:30 | Backend hello world on Render, Railway or Fly with a stable URL |
| 14:00 | Webhook: reply 200 right away, process in the background, drop duplicate message ids. Download the voice note and transcribe it with the vocabulary hint. **WhatsApp go/no-go** |
| 15:30 | Compare the two transcription providers on 5 audios and pick one. Request **segment timestamps** (the web player needs them) |
| 16:30 | Reply to the caregiver with `confirmation_text`. Identify the caregiver by phone number; ask "which patient?" if they have several |
| 17:00 | **End-to-end: audio -> record -> alert -> view** |
| 19:30 | `eval/run_eval.py` printing the `AGENTS.md` section 11 metrics, magic-link backend, README status table, backup demo video |

## Shared items and who owns them

1. **Patient, report, versions, corrections and query endpoints.** Dev A writes them in a separate router file (proposed: `backend/app/api.py`); Dev C includes it from `main.py` with one line. Add the file to `AGENTS.md` section 9 in the same commit.
2. **Magic-link backend** (`POST /auth/link`, single-use tokens): Dev C. Dev B builds only the landing page.
3. **Audio timestamps for citations.** Dev C delivers transcript segments with times, Dev A maps each quote to its segment, Dev B plays that fragment. Agree on the segment format before 14:00.
4. **Eval cases.** `eval/cases.csv` has 2 of 20. Dev A writes the text cases (keep at least 5 marked unseen). All three record the audio versions for voice variety. Never commit audio.
5. **README "Functional / Simulated / Pending" table.** Dev C keeps it current; each dev updates their own row when their part lands.

**Critical path:** Dev C's transcription -> Dev A's `process_report` -> Dev B's real-data view. If anyone is blocked at 17:00, the other two help unblock before doing anything else.
