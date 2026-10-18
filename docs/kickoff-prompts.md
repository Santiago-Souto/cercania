# Kickoff prompts for Claude Code

Open Claude Code in the repo root (it reads `CLAUDE.md` -> `AGENTS.md` automatically) and paste ONE prompt, depending on your role. Each role works in its own folder to avoid merge conflicts. Commit small and often; pull before you push.

## Shared first step (everyone, together, ~30 min)

```
Read AGENTS.md and docs/contract.md fully. Then, without writing feature code yet,
confirm the stack in AGENTS.md section 8 and list any inconsistency between the
two files. Propose the backend project scaffold (FastAPI), the DB schema in
backend/app/models.py matching section 5, and backend/app/seed.py with 3 fictional
patients, care plans, and a few days of history. Ask me before choosing anything
not already decided in AGENTS.md.
```

## Role: brain (extraction, comparison, query)

```
You are the "brain" owner per AGENTS.md section 9. Work only in backend/app/extract.py,
compare.py, query.py, models.py, seed.py and backend/tests/. Follow docs/contract.md
exactly (ProcessResult shape, quote rules, alert types).
Build, in this order, with tests for each:
1. extract.py: transcript -> items JSON using Claude structured output; one verbatim
   quote per item; null when not mentioned; never infer.
2. quote verification in code (normalized substring match). Unverified quotes must
   not drive alerts.
3. compare.py: missing checklist items, omissions vs care plan (medication times),
   changes vs previous days. No model calls in this file.
4. query.py: retrieve only the patient's relevant reports, answer with citations
   that verify against the cited transcript; return "unclear" when records do not
   contain the answer.
Never diagnose or suggest doses. Show me test output before saying anything is done.
```

## Role: web

```
You are the "web" owner per AGENTS.md section 9. Work only in web/. Build against
fake data shaped exactly like docs/contract.md; do not wait for the backend.
Two views from the same data: caregiver (patient profile, timeline, query screen)
and family (read-only summary and alerts). Each datum shows its citation and can
play the audio fragment. Magic-link access. Clear progress and error messages.
Done when someone who has never seen the project opens the link and understands
the last shift without explanation. No extra roles, no push notifications.
```

## Role: infra and input (web reports, transcription, eval)

```
You are the "infra/input" owner per AGENTS.md section 9. Work in backend/app/main.py,
web_reports.py, transcribe.py and eval/. Priorities in order:
1. Deploy a hello-world with a stable public URL.
2. POST /patients/:id/reports (text or audio) that dedupes by client id and takes
   the caregiver from the session.
3. Transcribe a recorded voice note. Compare two providers on
   5 real audios and report the word-error evidence before choosing. Pass the
   patient's care-plan vocabulary as a hint.
4. Show "I recorded: ..." and the missing items using the brain's ProcessResult.
5. eval/run_eval.py reading eval/cases.csv; print the metrics in AGENTS.md section 11.
Cut rule: if a recorded voice note does not flow end to end by 14:00 Saturday, fall
back to typed text and mark audio as Pending in README.md.
Never commit audio or secrets.
```
