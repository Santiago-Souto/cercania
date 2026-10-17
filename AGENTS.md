# AGENTS.md

Context and operating rules for any coding agent (or human) working in this repo.
Read this fully before changing code. Keep it updated: if reality and this file disagree, fix the file in the same commit.

## 1. What we are building

A care-handoff assistant for caregivers of dependent people (e.g. older adults in a residential center).

- A caregiver sends an end-of-shift **voice note via WhatsApp** to a bot. No app install. The same report can also be sent from the web app (audio or text); both go through the same pipeline.
- The system transcribes it, extracts structured data, **compares it against the patient's care plan and history by code**, flags omissions/changes, and stores everything on a web app.
- The next shift (or a family member) can **query the record in natural language** and gets answers **with a citation to the exact fragment of the original report**.

Product name: **CercanIA** (always written with capital "IA"; repo `Santiago-Souto/cercania`).

One-line pitch: *the shift handoff that doesn't get lost.*

Product focus right now: **build the product first; sales/business model comes later.**

## 2. Hackathon constraints (these decide priorities)

Event: Build 101, Oct 17-18 2026. Venue open Sat 09:00-21:00, Sun 09:00-16:00. Pitch: 3 min demo + 3 min jury Q&A.

Eligibility gate (checked BEFORE scoring):
- AI must be central, real and integrated. If removing the AI leaves the main function intact, we are disqualified.
- The main flow must work **live on inputs we did not prepare**. No hardcoded answers, no preloaded results presented as AI output.
- Anything simulated or pending must be **declared** (see README "Functional / Simulated / Pending").
- A technical review reads the repo and git history. Start clean; no substantial prior work.

Rubric weights: working product 35%, problem and user value 25%, AI quality 20% (needs a simple quality check), UX 10%, originality 10%. Complexity and tool count earn nothing. Ties break on working product, then user value.

**Implication: a smaller flow that never breaks beats a bigger one that sometimes does.**

## 3. Core principle

**The model reads and explains. Code calculates and verifies.** The LLM never decides doses, schedules, counts or alerts on its own. Every extracted fact carries a verbatim quote, and code checks that the quote exists in the transcript.

## 4. Pipeline

```
WhatsApp voice note                     web app report (audio or text)
  -> webhook (ack immediately,           -> POST /patients/:id/reports
     process async, dedupe by message id)   (dedupe by client-generated id)
  -> download audio                      -> (audio only) same transcription step
     ... both continue identically ...
  -> transcription (with patient-specific vocabulary hint)
  -> extraction (LLM, JSON schema, quote per field, null if not mentioned)
  -> quote verification (code: substring/normalized match against transcript)
  -> comparison (code, no model): vs care plan, vs previous days, vs required checklist
  -> alerts + missing-item list
  -> bot replies to caregiver: "I recorded: ... Is that right?" (+ asks for missing items)
  -> stored as a versioned report
  -> web app timeline + natural-language query with cited answers
```

Target: confirmation message back to the caregiver in **under 10 seconds**.

### Required checklist per report
Appetite, sleep, urination/diuresis, medication, mood, mobility, pain, incidents. Code detects which items were **not mentioned**; the bot then asks about them.

## 5. Data model (design rules)

Entities: `patient`, `care_plan` (medication with schedule and dose, indications, allergies), `user` (name, email, WhatsApp number = identity), `membership` (user + patient + role, see section 6), `invite` (pending membership by phone or email), `login_code` (hashed 6-digit code, expiry, used flag), `report`, `report_item`, `alert`, `patient_message` (how the patient feels, or a help request), `message` (family <-> health team thread per patient).

Rules:
- `report` stores: original audio reference, transcript, timestamp, sender, **version**. Corrections create a **new version**; previous versions stay visible and immutable (this is the evidence trail).
- `report_item` stores: item type, value, **verbatim supporting quote**, verification status.
- `alert` types: `omission` (plan vs report), `change` (vs usual), `missing_item` (checklist).
- Idempotency: processing the same WhatsApp message id twice must not create two reports.
- All seed/demo data is **fictional**. Never commit real audio, names or health data.

## 6. Roles and access (keep it minimal)

One web app, same data, a view per role. Roles are per patient (`membership`): the same person can be caregiver of one patient and family of another.

| Role | Can do |
|---|---|
| Caregiver | Send reports (WhatsApp or web), confirm/correct, query, see timeline and alerts, add patients and invite people |
| Health team (doctor, nurse, hospital/institution) | See assigned patients, reports, alerts and query; reply to family messages |
| Family | Read-only summary and alerts; message the health team |
| Patient | Only two actions: tell how they feel (audio or text) and press "I need help" |

Auth: sign up with name, email and WhatsApp number -> the bot sends a **6-digit code** to that WhatsApp -> code entered on the web. Codes are single-use, expire in 10 minutes, are stored hashed and are rate-limited per number. No passwords. Outbound WhatsApp messages outside the 24h window need an approved authentication template (or, in the sandbox, the user must join first); verify with the provider's docs. Invited users get the role from their invite after their first login.

## 7. Safety rules (non-negotiable)

- **Never diagnose. Never suggest, change or compute doses.** Record, compare, alert.
- If something is ambiguous, **ask or say "unclear"**. Never guess.
- Red-flag phrases (fall, chest pain, breathing difficulty, etc.) trigger a **fixed-rule** message: "contact emergency services or the physician." This is a safety net, not the product's core.
- Patient "I need help" is a **fixed rule**, never routed through the model: notify every caregiver and health-team member of that patient right away and show the patient "help is on the way; if it is an emergency, call emergency services". Patient "how I feel" messages go through the red-flag phrase list too.
- Family <-> health team messages are human-to-human. The model never answers them, and the thread always shows "not for emergencies".
- Do not claim legal protection. The product creates a *record of what was reported*.
- Not a replacement for the clinical record. No integration with health-system records (out of scope, see section 10).

## 8. Proposed stack (confirm or edit; update this section when decided)

- Backend: Python + FastAPI
- Web: **Next.js** (decided), mobile-first, usable on desktop at a centered ~480px column. UI copy in Spanish (Río de la Plata). **Design source of truth: `docs/design/DESIGN.md`** (tokens, components, screen → route → ticket map) with artboard snapshots in `docs/design/screens/`. UI changes start in the design, then the code.
- DB: Postgres (Supabase) or SQLite if time-constrained
- Transcription: Whisper-class API (OpenAI or Groq); fallback AWS Transcribe with custom vocabulary
- LLM: Claude via API. Start with `claude-sonnet-5-5`; use `claude-haiku-5-5` if latency demands. Use structured JSON output / tool use.
- WhatsApp: Twilio sandbox first, or Meta Cloud API test number. **Cut rule: if a real voice note does not flow end-to-end by 14:00 Sat, switch to a Telegram bot or a web recorder and list WhatsApp as Pending.**
- Deploy: any host with a stable public URL (Render, Railway, Fly). Deploy "hello world" first.
- Secrets only via environment variables. `.env` is gitignored; commit `.env.example` only.

## 9. Repo layout and ownership

```
backend/app/
  main.py          API + webhook (ack fast, process async)
  whatsapp.py      receive, download audio, reply            [infra/input owner]
  transcribe.py    audio -> text with vocabulary hint        [infra/input owner]
  extract.py       text -> JSON with quotes                  [brain owner]
  compare.py       plan/history/checklist logic, no model    [brain owner]
  query.py         cited natural-language answers            [brain owner]
  models.py        schema                                    [brain owner]
  seed.py          2-3 fictional patients + care plans       [brain owner]
web/               Next.js app, one view per role            [web owner]
                   sign-up + code, my patients, add patient + roles,
                   patient home, report, alerts, ask, new report,
                   family view, family<->health team messages, patient view
eval/
  cases.csv        20 cases with expected output
  run_eval.py      runs cases, prints metrics                [infra/input owner]
docs/contract.md   endpoints and data shapes (source of truth for integration)
docs/design/       DESIGN.md + screen snapshots (source of truth for the UI)  [web owner]
README.md          Functional / Simulated / Pending
.agents/skills/    shared agent skills, tool-agnostic (.claude/skills is a symlink here)
```

Contract first: the web owner builds against fake data from `docs/contract.md` and must not wait on the backend. Change the contract only by editing `docs/contract.md` in the same commit as the code.

Core interface:
`process_report(patient, caregiver, transcript, audio, message_id) -> { record, missing_items, alerts }`

Endpoints (initial): `GET /patients/:id`, `GET /patients/:id/reports`, `POST /patients/:id/query` (question -> answer + citations).

## 10. Out of scope (do not build)

Health-system / clinical-record integration, push notifications (alerts and help requests go out by WhatsApp message), passwords / OAuth / SSO, voice replies from the agent (text confirmation first; audio reply only if time remains Sunday), roles beyond the four in section 6, AI answers inside family <-> health team messages.

**Priority order (scope was widened on Sat 13:45; the critical path still comes first):**
1. Critical path: voice note or web report in -> verified record + alerts -> cited query, and the views that show it.
2. Sign-up with 6-digit code, my patients, add patient + roles.
3. Patient view (how I feel + I need help).
4. Family <-> health team messages (bonus: first to cut).

If a lower item threatens a sync point in section 14, stop it and list it as Pending in the README.

## 11. Quality check we must be able to show (AI quality, 20%)

`eval/cases.csv` with 20 fictional reports recorded by different team voices (noise, rush, regional slang), some with **planted omissions** vs the care plan and some missing checklist items.
`eval/run_eval.py` prints: fields extracted correctly, omissions detected, missing items detected, false alarms, and quote-verification pass rate. One number on screen is worth more than a long explanation.

Rule: never tune the prompt against the same cases we will demo with and then call it generalization. Keep at least 5 cases unseen until the end.

## 12. Definition of done (per area)

- Brain: given a transcript, returns record + missing items + alerts, every quote verified.
- Web: someone who has not seen the project opens the link and understands the last shift with no explanation; progress and error messages are clear; each datum shows its citation and plays the audio fragment.
- Infra/input: a voice note sent from a phone returns a confirmation in under 10 s; duplicate deliveries are ignored; eval script runs from one command.

## 13. Working agreements for agents

- Make small commits with clear messages. Never commit secrets, audio, or real personal/health data.
- Agent config lives in `.agents/` so it works with any coding agent. Add skills to `.agents/skills/<name>/SKILL.md`; do not put them under a tool-specific folder. Use `linear-ticket-writer` when creating or rewriting Linear tickets, and `ticket-to-pr` to take a ticket from worktree to a PR that closes it.
- Prefer the simplest thing that keeps the critical path working. If a task threatens the critical path, stop and flag it.
- Do not add dependencies without need; note any new one in the commit message.
- Handle errors visibly: the user must get a clear message instead of a silent failure.
- Do not simulate AI behavior. If something is mocked for development, mark it in code and in README under "Simulated".
- Before declaring work done: run the eval script and the happy-path flow end to end.
- When unsure about a provider's current limits, pricing or API behavior, check its documentation instead of relying on memory.

## 14. Timeline and sync points (Sat Oct 17)

| Time | Must exist |
|---|---|
| 12:30 | Contract, schema, seed data, hello-world deployed |
| 14:00 | Voice note transcribing (WhatsApp or fallback). Brain processes text. Web shows fake data. **WhatsApp go/no-go.** |
| 17:00 | First end-to-end integration: audio -> record -> alert -> view. Most important checkpoint. |
| 19:30 | Feature freeze. Bugs, eval cases, error handling, README only. |
| 21:00 | Venue closes. Everything deployed. Backup demo video recorded. |
| Sun | Polish, pitch rehearsal, Q&A prep. No new features. |

## 15. Pitch notes (so the product supports them)

Problem: the shift handoff gets lost. Live demo: a juror dictates a report, sees the structured record and an omission alert, then asks a question and gets a cited answer. Close by stating limitations first (no diagnosis, fictional data, simulated parts). Always keep a recorded backup of the demo and text input as a fallback to audio.

## 16. Open decisions

- Stack confirmation (section 8; web is decided: Next.js).
- WhatsApp authentication template for the 6-digit code vs sandbox join (section 6).
- Which transcription provider wins the 5-real-audio test.
- WhatsApp provider vs fallback channel (decided at 14:00).
- Final checklist item list (section 4) once validated with a caregiver contact.
