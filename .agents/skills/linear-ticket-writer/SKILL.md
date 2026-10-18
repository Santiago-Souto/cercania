---
name: linear-ticket-writer
description: Write or rewrite Linear ticket descriptions for the CercanIA team (CIA) so any dev or agent can pick one up and finish it without asking. Use when creating a CIA ticket, improving a vague one, or bulk-rewriting ticket descriptions.
---

# Linear ticket writer (CercanIA)

A good ticket here answers: what done looks like, which files I touch, what I depend on, and what I must not build. Everything comes from the repo, never from imagination.

## Sources (read before writing)

1. `AGENTS.md` — rules, Definition of Done (§12), safety rules (§7), out of scope (§10), timeline (§14).
3. `docs/contract.md` — exact data shapes and endpoints. Reference field names, never paraphrase them.
4. The current ticket description (via whatever Linear access you have: MCP, API or CLI). Keep every fact it already has.

If a source does not say something, leave it out or write `TBD — ask <owner>`. Never invent requirements, times or numbers.

## Template

```markdown
**Owner:** Dev X (<area>) — <handle> · **Due:** HH:MM Sat · **Files:** `path`, `path`

## Why
One or two sentences: what this unblocks on the critical path (voice note -> verified record + alerts -> cited query).

## Acceptance criteria
- [ ] Testable statement (an input and the observable result)
- [ ] ...

## Contract
Contract fields/endpoints this touches (`ProcessResult.items[].quote_verified`, `GET /patients/{id}`...). "None" if not applicable.

## Depends on / Unblocks
- Depends on: CIA-n (why)
- Unblocks: CIA-n (why)

## Out of scope
- Things a reasonable dev might add but must not (cite AGENTS.md §10 / §7 where relevant).

## Real or simulated
What must be real for the demo; anything mocked must be marked in code and in README "Simulated".

## How to verify
Command or manual steps that prove the criteria (pytest, curl, eval script, open the URL).
```

## Rules

- Acceptance criteria are checkable by someone else: name the input and the expected output. Avoid "works well", "clean", "robust".
- Pull safety rules into the criteria when relevant: the model never decides doses/alerts (sole exception: emergency triage in `triage.py`, with fixed reply text and recipients chosen by code), every quote is verified by code, `null` when not mentioned.
- Wrap every file name in backticks. Linear turns a bare `name.py` into a broken `http://name.py` link, and it can do this even to a backticked name placed right after an issue mention, so reword if it happens.
- Keep it short. A ticket should fit on one screen; link to the docs instead of copying them.
- Only reference CIA IDs that exist in the CercanIA team.
- Do not change title, assignee, priority, status or due date unless the user asks. Only the description.
- Bulk rewrites: draft one ticket, show it to the user, and wait for approval before saving the rest. Then update only the description of each ticket and report which tickets changed.
- If a rewrite reveals a gap or conflict between docs (e.g. a task with no owner), flag it to the user instead of resolving it silently.
