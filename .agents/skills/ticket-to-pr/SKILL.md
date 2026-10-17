---
name: ticket-to-pr
description: Take a CercanIA Linear ticket (CIA-n) from start to a pull request that closes it - understand intent, create a worktree on the ticket's branch, plan, implement, verify (tests, eval, happy path) and open the PR. Use when asked to "work on CIA-n", "pick up a ticket" or "ship this ticket".
---

# Ticket to PR (CercanIA)

One ticket -> one worktree -> one branch -> one PR that closes the ticket. Follow the phases in order. Each phase has a gate; do not skip one to save time. A smaller change that never breaks beats a bigger one that sometimes does (AGENTS.md §2).

Tool-neutral: use whatever Linear access you have (MCP, API or CLI), `git`, and `gh`. If your agent has helper skills for brainstorming, planning, TDD or code review, use them inside the matching phase; this skill still decides the order and the gates.

## 1. Understand (intent before code)

1. Read the ticket: title, description, assignee, status, relations, comments.
2. Read what it points to: `AGENTS.md` (always §3 core principle, §7 safety, §10 out of scope, §12 definition of done), `docs/contract.md`, `docs/tasks.md`, and the files listed in the ticket.
3. Read the code that already exists in those files and their callers. Never plan against code you have not opened.
4. Write a short **intent brief** back to the user (5-8 lines):
   - The problem in one sentence, from the user's point of view (caregiver, family, next shift, juror).
   - What done looks like: the acceptance criteria, restated as observable checks.
   - What is out of scope.
   - Assumptions you are making and open questions.
5. **Gate:** if anything blocks a correct implementation (ambiguous criteria, a contract gap, a dependency ticket not done, the ticket conflicts with AGENTS.md), ask the user now. Ask only what the docs cannot answer, a few questions at a time. If the ticket is vague, rewrite it first with the `linear-ticket-writer` skill.

## 2. Worktree on the ticket's branch

1. Get the branch name from Linear (the issue's git branch name, e.g. `<handle>/cia-5-...`). If the prefix is another person's handle, keep the `cia-n-...` part and use your own prefix: Linear links PRs by the `CIA-n` ID in the branch name, not by the prefix.
2. Fetch and create the worktree from the latest `main`:
   ```bash
   git fetch origin
   git worktree add ../cercania-cia-<n> -b <branch> origin/main
   ```
   If the branch already exists on the remote, check it out instead of creating it. If your agent already runs inside a fresh worktree for this task, rename or create the branch there instead of nesting another worktree.
3. Move the ticket to **In Progress** and assign it to the person doing the work if it has no assignee. (With the Linear-GitHub integration on, pushing the branch also does this.)
4. Work only inside that worktree from now on.

## 3. Plan

1. Write a plan of small steps. Each step names the files it touches and how it will be checked (a test, a command, a page to open).
2. Stay inside the files the ticket owns (AGENTS.md §9 / `docs/tasks.md`). If you need to touch another owner's file or the contract, say so in the plan.
3. Order steps so the critical path works early: a thin end-to-end slice first, polish last.
4. Write tests first where the behavior is checkable in code (quote verification, compare rules, idempotency, endpoint shapes).
5. **Gate:** show the plan to the user and wait for approval before writing code. If the user said to run autonomously, post the plan as a comment on the ticket and continue.

## 4. Implement

- Follow the plan step by step; mark each done as you go. If reality differs from the plan, update the plan and say why.
- Small commits with clear messages that start with the ticket ID: `CIA-5: verify quotes against normalized transcript`.
- Rules that never bend here:
  - The model reads and explains; code calculates and verifies. No doses, schedules, counts or alerts decided by the model.
  - Every extracted fact carries a verbatim quote that code verifies.
  - `null` / `unclear` instead of guessing.
  - Never commit secrets, audio or real personal/health data. Seed data is fictional.
  - Anything mocked is marked in code and listed in README "Simulated". Never present a mock as AI output.
  - Errors reach the user as a clear message, never a silent failure.
  - No new dependency without need; name it in the commit message.
- If the contract changes, edit `docs/contract.md` in the same commit as the code.

## 5. Verify

Run all of these from the worktree and keep the output for the PR:

1. Unit tests: `pytest backend/tests` (and web tests if the ticket touches `web/`).
2. Eval: `python eval/run_eval.py` once it exists. Compare against the last numbers on `main`; a drop in quote-verification pass rate or new false alarms blocks the PR. If the script does not exist yet, say so in the PR instead of skipping silently.
3. Happy path: run the flow the ticket affects end to end (voice or text in -> record + alerts -> web view / cited answer) on an input you did not prepare.
4. Walk the acceptance criteria one by one and tick each with evidence. Anything not met is either fixed now or listed as not done.
5. Self-review the diff: run your agent's code-review / simplify tooling if available; otherwise read the full diff for bugs, leftover debug code, secrets and scope creep.
6. **Gate:** do not open the PR while a check fails, unless the user agrees and the PR says so plainly.

## 6. Ship the PR

1. Update README "Status" / "Simulated" rows and `AGENTS.md` if reality changed (e.g. a new file in §9).
2. Rebase on the latest `origin/main`, re-run tests, push the branch.
3. Open the PR with `gh pr create` against `main`:
   - Title: `CIA-<n>: <ticket title without the [Dev X] HH:MM prefix>`
   - Body:
     ```markdown
     Closes CIA-<n>

     ## What
     One paragraph: the change and why.

     ## Acceptance criteria
     - [x] criterion — evidence (test name, command output, screenshot)
     - [ ] criterion not met — why, and the follow-up ticket

     ## Verification
     Tests: <result>. Eval: <key numbers vs main>. Happy path: <what you ran>.

     ## Simulated / not done
     Anything mocked or pending, or "None".
     ```
   `Closes CIA-<n>` makes Linear close the ticket when the PR merges.
4. Move the ticket to **In Review** if the integration did not, and post the PR link on the ticket.
5. Report to the user: PR link, what changed, verification results, anything left. Do not merge unless the user asks.

## When to stop and ask

- The ticket depends on work that is not merged yet.
- The change would touch another owner's files or the contract without agreement.
- A check fails and the fix is outside the ticket's scope.
- Anything that would break the critical path before a sync checkpoint (AGENTS.md §14).
