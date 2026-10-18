# AGENTS.md

Context and operating rules for any coding agent (or human) working in this repo.
Read this fully before changing code. Keep it updated: if reality and this file disagree, fix the file in the same commit.

## 1. What we are building

A care-handoff assistant for caregivers of dependent people (e.g. older adults in a residential center).

- A caregiver sends an end-of-shift report from the **web app**, as a voice note or as text, from their phone or a computer. Decided Oct 18 (CIA-47): the web app is the only channel.
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

**One deliberate exception: emergency triage.** The model decides whether a message describes an emergency (decided Oct 17; no deterministic phrase list for now). Everything around that decision stays in code: the reply text is fixed, the recipients come from the database, and the model's supporting quote is verified like any other quote. An unverified quote **never suppresses** an emergency; it is shown as unverified.

## 4. Pipeline

```
web app report (POST /patients/:id/reports, audio or text)
  (sender = session user, dedupe by client id, patient from the URL)
  -> permission check (code): only roles that can send reports (caregivers)
  -> transcription (with patient vocabulary hint); text reports skip this
       empty/unintelligible -> ask to resend, stop
  -> triage (LLM): emergency yes/no + reason + quote
  -> route by triage result and sender role (see 4.1, 4.2)
  -> caregiver, any triage result: extraction (LLM, JSON schema, quote per field, null if not mentioned)
  -> quote verification (code: substring/normalized match against transcript)
  -> comparison (code, no model): vs care plan, vs previous days, vs required checklist
  -> alerts + missing-item list
  -> stored as a report (new versions only via corrections in the web)
  -> the web app shows the confirmation to the sender
  -> web app timeline + natural-language query with cited answers
```

Target: confirmation shown to the caregiver in **under 10 seconds**. Triage and extraction may run concurrently for caregivers. If both are needed, the emergency reply goes out first and does not wait for extraction.

### 4.1 Routing by sender

The sender is the logged-in session user; their role comes from `patient_access` for the patient in the URL. Checked in code, never by the model. Unknown phone numbers cannot reach the pipeline: they have no session.

| Sender | Triage: no emergency | Triage: emergency |
|---|---|---|
| Caregiver | Shift report: extraction, comparison, confirmation | Shift report **plus** the emergency flow (4.2) |
| Family / Doctor / Patient (`process_report` only; the web report endpoint accepts caregivers, and the patient raises alarms through the patient view) | Nothing stored (`not_a_report`). | Emergency report (no checklist extraction) **plus** the emergency flow (4.2) |

- Each message is a **new report**. A follow-up note (e.g. answering a missing item) is a separate report; corrections to a recorded report are made only in the web and create a new `report_version`.
- The confirmation text lists what was recorded and what is missing, and invites the caregiver to send another report. It does not wait for a "yes".
- One report = one patient. The report is always filed under the patient in the URL; a note that covers several patients should be sent once per patient.

### 4.2 Emergency flow

Triggered when triage says emergency, for any registered sender.

1. **Answer the sender immediately** with the fixed message: contact emergency services or the physician. No checklist questions in this reply.
2. **Store** the report with `red_flag = true` and create an alert of type `emergency`, carrying the triage reason and quote, plus that quote's verification status.
3. **Notify in the web inbox**: the other caregivers and family members with access to that patient (never the patient, never the sender). Record each notification on the alert and in the `notification` table; the app polls the inbox every ~5 s and shows a browser Notification while the tab is open. The patient's **emergency contact** (name + phone, reusing the `health_provider_*` columns) has no inbox, so it is never notified by the server. Wherever the web shows an emergency (result after sending a report, banner on the patient, emergency alerts) it adds a `tel:` call button to that number, labeled with its name, or "Llamar al 911" when none is set. The fixed reply text does not change; nothing is called automatically (CIA-51).
4. The web shows the emergency as a banner on the patient and in the alerts panel.

There is no push channel outside the app: a recipient sees the emergency when they open the web app (or have it open). If the inbox write fails, the failure is logged on the server (dispatch is idempotent, so it can be re-run); never fail silently.

If triage itself fails (model error/timeout), the sender still gets a message that includes the fixed emergency line, and the report is stored with `triage_status = failed` so it is visible.

### Required checklist per report
Appetite, sleep, urination/diuresis, medication, mood, mobility, pain, incidents. Code detects which items were **not mentioned**; the confirmation lists them so the caregiver can send another note.

## 5. Data model (design rules)

Schema lives in `backend/app/models.py`. Entities: `person` (anyone who logs in; name, email, phone number = identity; "user" in the contract), `patient_access` (person + patient + role; "membership" in the contract, see section 6), `invite` (pending membership by phone number), `login_code` (hashed 6-digit code sent by SMS, expiry, attempts, used flag), `auth_session` (hashed web session token), `patient` (optionally an emergency contact: name + phone in the `health_provider_*` columns, exposed as `emergency_contact`; a call button target, never notified by the server; `archived_at` when a caregiver removed it, which also drops every membership and pending invite), `care_plan` (versioned; indications, allergies) + `medication` (schedule and dose text), `report`, `report_version`, `report_item`, `alert`, `file`, `patient_message` (how the patient feels, or a help request), `message` (family <-> health team thread per patient), `pre_registration` (a role an admin assigned to a phone that has not signed up yet) and `role_change` (audit log of every role an admin assigned or a sign-up applied). `person.is_admin` marks a global admin (CIA-48). `message_read` records who opened the thread after each message.

Rules:
- Structured data in Postgres; binaries (audio, images, documents) in object storage. `file` stores only the storage path and metadata.
- `report` stores what was received: audio (via `file`), transcript, timestamped segments, timestamp, sender (any role), message id, `kind` (`shift` from a caregiver, `emergency` from another role) and the triage result. Written once. An `emergency` report has no checklist items.
- `report_version` stores what was recorded. Corrections create a **new version**; previous versions stay visible and immutable (this is the evidence trail).
- `report_item` stores: item type, value, coarse `level` (for code comparison over time), item `details` (e.g. medication doses), **verbatim supporting quote**, verification status. One row per checklist item; `value` null = not mentioned.
- `alert` types: `omission` (plan vs report), `change` (vs usual), `missing_item` (checklist), `emergency` (triage; carries the web inbox notifications created).
- Idempotency: processing the same web report client id twice must not create two reports.
- All seed/demo data is **fictional**. Never commit real audio, names or health data.

## 6. Roles and access (keep it minimal)

One web app, same data, a view per role. Roles are per patient (`patient_access`, "membership"): the same person can be caregiver of one patient and family of another. Permissions live in `ROLE_PERMISSIONS` in `backend/app/models.py`; endpoints return `403 forbidden` when the role lacks one.

| Role | Can do |
|---|---|
| Caregiver | Send reports (web, audio or text), confirm/correct, query, see timeline and alerts, add patients (with their initial care plan and optional emergency number), remove a patient (archived: nobody keeps access, records stay stored), edit the emergency number, and invite people |
| Health team (doctor, nurse, hospital/institution) | See assigned patients, reports, alerts and query; reply to family messages. The **doctor** is the only role that edits the care plan after creation (each edit = new plan version); the doctor can also edit the emergency number |
| Family | Read-only summary and alerts; message the health team |
| Patient | Only two actions: tell how they feel (audio or text) and press "I need help". **No access to reports or alerts about them.** |
| Admin (global, not per patient) | Only lists people and assigns roles (including pre-registering a phone that has not signed up). **No access to reports, alerts, care plans or messages.** Set by hand in the database, from an `admin` pre-registration, or by another admin on an existing person, always after a confirmation (decided Oct 18, CIA-48) |

**Who gets which role (decided Oct 18, CIA-48), in code in `backend/app/roles.py`:**
- **Self sign-up is always patient:** a new person with no admin pre-registration and no pending invite gets their own patient profile and the `patient` role.
- **Caregivers invite family or patients.** Family is always tied to one of the caregiver's patients. A patient invite is either that patient's own login, or, without a patient, a new profile created when the person accepts, with the inviting caregiver as its caregiver.
- **Every other role is assigned by an admin**, to registered people or by pre-registering a phone (caregivers and admins may be pre-registered without a patient). Replacing something that exists needs the admin's explicit confirmation (`409` first).
- **Only caregivers create patients** (they become the patient's caregiver).

Any role can raise an emergency (a caregiver in a report, the patient in the patient view; section 4.1); only caregivers send shift reports. Raising an emergency gives the sender no extra read access.

The patient is the subject of the profile; optionally they also have their own login with the `patient` role. Dose text is written by people (caregiver at creation, doctor afterwards); code never computes or suggests doses.

Auth: sign up with name, email and phone number -> a **6-digit code by SMS** (Twilio; decided Oct 18, CIA-43) -> code entered on the web -> session cookie. Codes are single-use, expire in 10 minutes, are stored hashed, lock after 5 wrong tries and are rate-limited per number. No passwords. The phone number is the person's identity; invites are matched on it. Invited users see the invite in the web app (matched on the phone their session proved; on "Mis pacientes" and on the patient view, plus a toast while the app is open) and get its role only when they accept it. A self-signed-up patient who accepts a patient invite to another profile has their own profile merged into it when nobody else has access to it and it has no reports. Only caregivers can invite, by phone number only (email is not verified, so it never grants access), and **only as family or patient** (decided Oct 18, CIA-48; replaces the CIA-34 rule that allowed any role): the health team and other caregivers are assigned by an admin. Email is contact info, not identity, and need not be unique. Login and sign-up never reveal whether a phone is registered. Corrections and reports take the author from the session, never from the request body.

## 7. Safety rules (non-negotiable)

- **Never diagnose. Never suggest, change or compute doses.** Record, compare, alert.
- If something is ambiguous, **ask or say "unclear"**. Never guess.
- Emergencies (the patient needs immediate help or their health is at risk: a fall, injury, chest pain, breathing difficulty, etc.) are detected by the **model in the triage step** (section 4.2). The reply is a **fixed message** written in code: "contact emergency services or the physician." The app never gives first-aid or clinical instructions. This is a safety net, not the product's core.
- When in doubt, triage leans to emergency: a false alarm costs less than a missed one.
- Patient "I need help" is a **fixed rule**, never routed through the model: notify every caregiver and health-team member of that patient right away and show the patient "help is on the way; if it is an emergency, call emergency services". Patient "how I feel" messages go through the same triage step, text or audio (audio is triaged on its transcript).
- Family <-> health team messages are human-to-human. The model never answers them, and the thread always shows "not for emergencies".
- Do not claim legal protection. The product creates a *record of what was reported*.
- Not a replacement for the clinical record. No integration with health-system records (out of scope, see section 10).

## 8. Proposed stack (confirm or edit; update this section when decided)

- Backend: Python + FastAPI
- Web: **Next.js** (decided), mobile-first, usable on desktop at a centered ~480px column. UI copy in Spanish (Río de la Plata). **Design source of truth: `docs/design/DESIGN.md`** (tokens, components, screen → route → ticket map) with artboard snapshots in `docs/design/screens/`. UI changes start in the design, then the code. **UI is shadcn/ui only** (themed with our tokens); no custom components or plain HTML unless strictly necessary.
- DB: **decided** Postgres on Supabase via SQLAlchemy 2.0 + psycopg 3 (`DATABASE_URL`); SQLite is the local default and fallback (same models). Files in Supabase Storage, private bucket, signed URLs.
- Transcription: **decided** Groq Whisper (`whisper-large-v3-turbo`, env `GROQ_API_KEY`) with a vocabulary prompt; word timestamps (`verbose_json`, `timestamp_granularities[]=word`) feed audio citations. Free tier, same key as the LLM tasks. The planned comparison with OpenAI Whisper was dropped (Oct 18).
- LLM: structured JSON output. Every call goes through `llm.py`, so any task can switch vendor by config: `<TASK>_MODEL=<provider>:<model>` with `groq` (`GROQ_API_KEY`), `anthropic` (`ANTHROPIC_API_KEY`) or `openai` (any other OpenAI-compatible endpoint via `LLM_BASE_URL` / `LLM_API_KEY`). Switch only if the eval says so. **Decided per task:**
  - Extraction (`extract.py`, transcript -> checklist items with quotes): **decided** Groq `openai/gpt-oss-120b` (strict JSON schema; same `GROQ_API_KEY` as transcription). One schema-constrained call, no tools; code verifies every quote. Override with `EXTRACT_MODEL`.
  - Cited query (`query.py`, reasoning across several reports): Groq `openai/gpt-oss-120b` (same key as extraction; switched from Claude Sonnet because no Anthropic key is configured). Override with `QUERY_MODEL`.
  - Emergency triage (`triage.py`, every message from a registered sender): Groq `openai/gpt-oss-120b` (switched from Claude Haiku for the same reason), small schema (`emergency`, `reason`, `quote`), separate call from extraction so it also covers non-caregivers. Override with `TRIAGE_MODEL`.
  - All three share Groq's free-tier limit (8,000 tokens/minute; one report = extraction + triage), so space out demo reports and eval cases (`run_eval.py --delay 30`), or move a task to another provider. On a 429, `llm.py` waits what the provider's `Retry-After` says (up to 15 s) and retries once; asked to wait longer, it fails at once.
- SMS (login code only): **decided** Twilio Programmable Messaging REST API via `httpx` (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` or `TWILIO_MESSAGING_SERVICE_SID`). A trial account only texts numbers verified in its console.
- Deploy: any host with a stable public URL (Render, Railway, Fly). Deploy "hello world" first.
- Secrets only via environment variables. `.env` is gitignored; commit `.env.example` only.

## 9. Repo layout and ownership

```
backend/app/
  main.py          API                                       [shared]
  sms.py           send the login code by SMS (Twilio)       [infra/input owner]
  transcribe.py    audio -> text with vocabulary hint        [infra/input owner]
  web_reports.py   POST /patients/{id}/reports (text/audio)  [infra/input owner]
  patient_messages.py  POST/GET /patients/{id}/patient-messages (help, feeling) [infra/input owner]
  ingest.py        single hand-off from channels to process_report [infra/input owner]
  roles.py         who gets which role: sign-up rule, pre-registration, caregiver check [shared]
  storage.py       voice notes in Supabase Storage, signed URLs [infra/input owner]
  deps.py          DB session + current person dependencies  [shared]
  errors.py        {error: {code, message}} shape and handlers [shared]
  schemas.py       Pydantic models for every endpoint (mirror contract) [shared]
  serializers.py   ORM -> contract dicts, one place          [shared]
  api/             web routes, one module per area: auth, admin, patients, reports, corrections, me, notifications, query, messages [shared]
  process.py       process_report: triage + extraction -> compare -> store [brain owner]
  notify.py        emergency notifications: web inbox [shared]
  llm.py           one JSON-schema call, any vendor          [brain owner]
  triage.py        text -> emergency yes/no + quote (LLM)    [brain owner]
  extract.py       text -> JSON with quotes                  [brain owner]
  segments.py      quote -> audio start/end from transcript segments (code) [shared]
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
docs/deploy.md     Render URLs, env vars, troubleshooting
docs/demo-script.md  3-minute live demo script
docs/design/       DESIGN.md + screen snapshots (source of truth for the UI)  [web owner]
README.md          Functional / Simulated / Pending
.agents/skills/    shared agent skills, tool-agnostic (.claude/skills is a symlink here)
```

Contract first: `docs/contract.md` is the source of truth for endpoints and data shapes. Change the contract only by editing `docs/contract.md` in the same commit as the code.

Core interface:
`process_report(patient, caregiver, transcript, audio, message_id, segments) -> { record, missing_items, alerts }`

Endpoints: see `docs/contract.md`.

## 10. Out of scope (do not build)

Health-system / clinical-record integration, any push channel outside the web app (decided Oct 18, CIA-47; alerts, help requests and emergency notifications go to the in-app web inbox, polled every ~5 s, plus the browser Notification API while the tab is open), passwords / OAuth / SSO, voice replies from the agent (text confirmation first; audio reply only if time remains Sunday), per-patient roles beyond the six in section 6 (caregiver, family, patient, doctor, nurse, institution; the global admin of CIA-48 assigns them and is not one of them), organizations or multi-tenant admins, AI answers inside family <-> health team messages.

**Priority order (scope was widened on Sat 13:45; the critical path still comes first):**
1. Critical path: voice note or web report in -> verified record + alerts -> cited query, and the views that show it.
2. Sign-up with 6-digit code, my patients, add patient + roles.
3. Patient view (how I feel + I need help).
4. Family <-> health team messages (bonus: first to cut).

If a lower item threatens a sync point in section 14, stop it and list it as Pending in the README.

## 11. Quality check we must be able to show (AI quality, 20%)

`eval/cases.csv` with 20 fictional reports recorded by different team voices (noise, rush, regional slang), some with **planted omissions** vs the care plan and some missing checklist items.
Include emergency cases (and look-alikes such as "sin caídas" or a fall that was already handled) so triage is measured too.
`eval/run_eval.py` prints: fields extracted correctly, omissions detected, missing items detected, false alarms, quote-verification pass rate, and emergencies missed / false emergencies. One number on screen is worth more than a long explanation.

Rule: never tune the prompt against the same cases we will demo with and then call it generalization. Keep at least 5 cases unseen until the end.

## 12. Definition of done (per area)

- Brain: given a transcript, returns record + missing items + alerts, every quote verified.
- Web: someone who has not seen the project opens the link and understands the last shift with no explanation; progress and error messages are clear; each datum shows its citation and plays the audio fragment.
- Infra/input: a voice note recorded in the web app returns a confirmation in under 10 s; duplicate deliveries are ignored; eval script runs from one command.

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
| 14:00 | Voice note transcribing from the web app. Brain processes text. |
| 17:00 | First end-to-end integration: audio -> record -> alert -> view. Most important checkpoint. |
| 19:30 | Feature freeze. Bugs, eval cases, error handling, README only. |
| 21:00 | Venue closes. Everything deployed. (No backup video: decided Oct 18, the live demo relies on its fallbacks.) |
| Sun | Polish, pitch rehearsal, Q&A prep. No new features. |

## 15. Pitch notes (so the product supports them)

Problem: the shift handoff gets lost. Live demo: a juror dictates a report, sees the structured record and an omission alert, then asks a question and gets a cited answer. Close by stating limitations first (no diagnosis, fictional data, simulated parts). No recorded backup video (team decision, Oct 18): the live demo relies on text input as a fallback to audio and on a second logged-in device. Step-by-step script: `docs/demo-script.md`.

## 16. Open decisions

- Stack confirmation (section 8; web is decided: Next.js).
- Twilio: trial (verified numbers only) vs a paid number for the demo; some countries need a registered sender for SMS.
- Final checklist item list (section 4) once validated with a caregiver contact.
- Emergency triage criteria (section 4.2): the prompt in `triage.py` is provisional. It currently treats a past event the message says was attended, with the patient now fine ("se cayó a la mañana, la vio el médico, está bien"), as **not** an emergency, and anything unclear as an emergency. Confirm or change.
- Whether to add a deterministic phrase list as a second safety net next to the model (rejected for now, Oct 17).
- Messages from family/doctor/patient that are not emergencies only get a link for now; revisit (e.g. family questions answered with `query.py`).
