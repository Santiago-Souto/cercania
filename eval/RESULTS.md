# Eval results

One entry per eval run, newest first. Paste the summary printed by
`python eval/run_eval.py --delay 30` and note the misses. Cases are fictional
text transcripts (`eval/cases.csv`); audio recordings are not part of these runs.

## Pending — 26 cases (14 dev, 12 unseen)

CIA-52 added six unseen cases (c021-c026): three emergencies (collapse, stroke-like signs in a long report, seizure) and three look-alikes (past fall seen by the doctor, past chest pain seen by the doctor, negated fall/choking/breathing). They were written before reading `triage.py` and no prompt changed. **Not run yet**: run `python eval/run_eval.py --delay 30` with a `GROQ_API_KEY` and paste the summary here, unseen split separate. The entry below covers only the original 20 cases.

## 2026-10-18 — 20 cases (14 dev, 6 unseen)

- Base commit: `555ab33` + CIA-24 changes (20 cases, database reset per case)
- Models: extraction and triage `groq:openai/gpt-oss-120b` (defaults, no overrides)
- Command: `python eval/run_eval.py --delay 30`; 20/20 cases `ok`, no errors

| Metric | Seen (dev, 14) | Unseen (6) | All (20) |
|---|---|---|---|
| Fields extracted (value + verified quote) | 67/68 (99%) | 31/32 (97%) | 98/100 (98%) |
| Omissions detected | 17/17 (100%) | 7/7 (100%) | 24/24 (100%) |
| Changes detected | 11/13 (85%) | 4/5 (80%) | 15/18 (83%) |
| Emergencies detected | 3/3 (100%) | 1/1 (100%) | 4/4 (100%) |
| Emergency false alarms | 0 | 0 | 0 |
| Missing items detected | 40/40 (100%) | 14/14 (100%) | 54/54 (100%) |
| False alarms | 2 | 0 | 2 |
| Quote verification pass rate | 67/67 (100%) | 32/33 (97%) | 99/100 (99%) |
| Latency per report (median / max) | 3.8s / 9.8s | 3.9s / 4.3s | 3.9s / 9.8s |

Misses:
- c004 (dev): expected `change:incidents` not raised. The slip "caught in time, no injury" was likely leveled as `none`; the expectation is debatable.
- c005 (dev): unexpected `change:mobility`. "Caminó con ayuda" was likely leveled `reduced`; the seed history treats it as `normal`.
- c013 (dev): mood ("desorientada otra vez") reported as not mentioned, so the `change:mood` alert was also lost.
- c016 (unseen): one quote failed verification, so that item did not count and one of the two expected changes was not raised (unverified values never raise alerts, by design).

Single run; the model is not deterministic, so numbers can move between runs.
