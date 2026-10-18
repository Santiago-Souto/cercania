"""Runs eval/cases.csv through the real process_report and prints the metrics
from AGENTS.md section 11, with seen (dev) and unseen cases separated.

    python eval/run_eval.py                  # all cases
    python eval/run_eval.py --split unseen   # only the held-out cases
    python eval/run_eval.py --json out.json  # also write per-case results
    python eval/run_eval.py --delay 30       # pause between cases (Groq free tier: ~2 reports/min)

Each run uses a fresh temporary SQLite database with the fictional seed data,
so it never touches the team's database. The database is restored to the seeded
state before every case, so each case is compared only against the seed history
(expected `change` alerts in cases.csv assume that) and the order or --split of
the cases does not change the results. Model calls are real (needs the API
key of the configured provider, see backend/app/llm.py); nothing here is simulated.

What "correct" means (scored by code, not by a model):
- field detected: an expected item came back with a value and a verified quote.
  The wording of the value is NOT judged (it is free text).
- missing item detected: an item the case says was not mentioned is in missing_items.
- omission detected: an expected `omission:<plan_ref>` alert came back.
- change detected: an expected `change:<item>` alert came back (change alerts carry `item`).
- emergency detected: a case expecting `emergency` got an emergency alert (triage).
  An emergency alert on a case that does not expect one is an emergency false alarm,
  reported on its own line and also counted in false alarms.
- false alarm: an omission/change/emergency alert the case does not expect, an item reported
  although the case says it was not mentioned, or an item flagged missing although
  it was mentioned.
- quote verification pass rate: returned quotes that code verified against the transcript.

A case fails when process_report raises or returns a status other than "ok". A
failed case keeps its expected counts with zero detections, so failures lower
every ratio instead of disappearing, and the run exits with code 1.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "eval" / "cases.csv"
MIN_UNSEEN = 5  # AGENTS.md section 11


# --- Cases -----------------------------------------------------------------------


@dataclass
class Case:
    case_id: str
    patient_id: str
    transcript: str
    expected_items: set[str]
    expected_missing: set[str]
    expected_alerts: set[str]  # "type:key", e.g. "omission:med_002"; "emergency" -> "emergency:"
    split: str


def _split_list(raw: str) -> list[str]:
    return [part.strip() for part in (raw or "").split(";") if part.strip()]


def _alert_spec(entry: str) -> str:
    """Alerts without a key (e.g. "emergency") match alert_key's "type:" form."""
    return entry if ":" in entry else f"{entry}:"


def load_cases(path: Path) -> list[Case]:
    with open(path, newline="", encoding="utf-8") as f:
        return [
            Case(
                case_id=row["case_id"],
                patient_id=row["patient_id"],
                transcript=row["transcript"],
                expected_items={entry.split("=", 1)[0].strip() for entry in _split_list(row["expected_items"])},
                expected_missing=set(_split_list(row["expected_missing_items"])),
                expected_alerts={_alert_spec(a) for a in _split_list(row["expected_alerts"])},
                split=(row.get("split") or "dev").strip(),
            )
            for row in csv.DictReader(f)
        ]


# --- Scoring (pure, tested in backend/tests/test_run_eval.py) ----------------------


@dataclass
class CaseScore:
    case_id: str
    split: str
    status: str
    seconds: float = 0.0
    error: str | None = None
    fields_expected: int = 0
    fields_detected: int = 0
    missing_expected: int = 0
    missing_detected: int = 0
    omissions_expected: int = 0
    omissions_detected: int = 0
    changes_expected: int = 0
    changes_detected: int = 0
    emergencies_expected: int = 0
    emergencies_detected: int = 0
    unexpected_alerts: list[str] = field(default_factory=list)
    invented_items: list[str] = field(default_factory=list)  # reported but not mentioned
    wrongly_missing: list[str] = field(default_factory=list)  # flagged missing but mentioned
    quotes: int = 0
    quotes_verified: int = 0

    @property
    def emergency_false_alarms(self) -> int:
        return self.unexpected_alerts.count(EMERGENCY)

    @property
    def false_alarms(self) -> int:
        return len(self.unexpected_alerts) + len(self.invented_items) + len(self.wrongly_missing)


SCORED_ALERT_TYPES = ("omission", "change", "emergency")
EMERGENCY = "emergency:"


def alert_key(alert: dict) -> str:
    return f"{alert.get('type')}:{alert.get('plan_ref') or alert.get('item') or ''}"


def failed_score(case: Case, seconds: float, error: str, status: str = "error") -> CaseScore:
    """A failed case still counts what was expected, with nothing detected."""
    return CaseScore(
        case_id=case.case_id,
        split=case.split,
        status=status,
        seconds=seconds,
        error=error,
        fields_expected=len(case.expected_items),
        missing_expected=len(case.expected_missing),
        omissions_expected=sum(1 for a in case.expected_alerts if a.startswith("omission:")),
        changes_expected=sum(1 for a in case.expected_alerts if a.startswith("change:")),
        emergencies_expected=int(EMERGENCY in case.expected_alerts),
    )


def score_case(case: Case, result: dict, seconds: float = 0.0) -> CaseScore:
    items = result.get("items") or []
    detected = {i["item"] for i in items if i.get("value") is not None and i.get("quote_verified")}
    reported = {i["item"] for i in items if i.get("value") is not None}
    missing = set(result.get("missing_items") or [])
    alerts = {alert_key(a) for a in result.get("alerts") or [] if a.get("type") in SCORED_ALERT_TYPES}
    expected_omissions = {a for a in case.expected_alerts if a.startswith("omission:")}
    expected_changes = {a for a in case.expected_alerts if a.startswith("change:")}
    quoted = [i for i in items if i.get("quote")]
    status = result.get("status", "missing_status")
    if status != "ok":
        detail = result.get("message") or result.get("confirmation_text") or ""
        return failed_score(case, seconds, f"process_report returned status={status!r} {detail}".strip(), status)

    return CaseScore(
        case_id=case.case_id,
        split=case.split,
        status=status,
        seconds=seconds,
        fields_expected=len(case.expected_items),
        fields_detected=len(case.expected_items & detected),
        missing_expected=len(case.expected_missing),
        missing_detected=len(case.expected_missing & missing),
        omissions_expected=len(expected_omissions),
        omissions_detected=len(expected_omissions & alerts),
        changes_expected=len(expected_changes),
        changes_detected=len(expected_changes & alerts),
        emergencies_expected=int(EMERGENCY in case.expected_alerts),
        emergencies_detected=int(EMERGENCY in case.expected_alerts and EMERGENCY in alerts),
        unexpected_alerts=sorted(alerts - case.expected_alerts),
        invented_items=sorted(reported & case.expected_missing),
        wrongly_missing=sorted(missing & case.expected_items),
        quotes=len(quoted),
        quotes_verified=sum(1 for i in quoted if i.get("quote_verified") is True),
    )


def ratio(num: int, den: int) -> str:
    return f"{num}/{den} ({100 * num / den:.0f}%)" if den else "n/a (no cases)"


def summarize(scores: list[CaseScore]) -> dict:
    """Failed cases stay in every denominator (with zero detections) and in latency."""
    times = [s.seconds for s in scores]
    return {
        "cases": len(scores),
        "errors": sum(1 for s in scores if s.error is not None),
        "fields": (sum(s.fields_detected for s in scores), sum(s.fields_expected for s in scores)),
        "omissions": (sum(s.omissions_detected for s in scores), sum(s.omissions_expected for s in scores)),
        "changes": (sum(s.changes_detected for s in scores), sum(s.changes_expected for s in scores)),
        "emergencies": (sum(s.emergencies_detected for s in scores), sum(s.emergencies_expected for s in scores)),
        "emergency_false_alarms": sum(s.emergency_false_alarms for s in scores),
        "missing": (sum(s.missing_detected for s in scores), sum(s.missing_expected for s in scores)),
        "false_alarms": sum(s.false_alarms for s in scores),
        "quotes": (sum(s.quotes_verified for s in scores), sum(s.quotes for s in scores)),
        "median_s": statistics.median(times) if times else None,
        "max_s": max(times) if times else None,
    }


def format_summary(title: str, summary: dict) -> str:
    lines = [f"== {title}: {summary['cases']} cases" + (
        f", {summary['errors']} FAILED (counted as zero detections)" if summary["errors"] else "")]
    lines += [
        f"   Fields extracted (value + verified quote): {ratio(*summary['fields'])}",
        f"   Omissions detected:                        {ratio(*summary['omissions'])}",
        f"   Changes detected:                          {ratio(*summary['changes'])}",
        f"   Emergencies detected:                      {ratio(*summary['emergencies'])}",
        f"   Emergency false alarms:                    {summary['emergency_false_alarms']}",
        f"   Missing items detected:                    {ratio(*summary['missing'])}",
        f"   False alarms:                              {summary['false_alarms']}",
        f"   Quote verification pass rate:              {ratio(*summary['quotes'])}",
        f"   Latency per report: median {summary['median_s']:.1f}s, max {summary['max_s']:.1f}s",
    ]
    return "\n".join(lines)


# --- Running against the real pipeline -----------------------------------------------


def prepare_backend(db_path: Path):
    """Points the backend at a fresh SQLite file, seeds it, returns (process_report, models, reset).

    reset() puts the database back to the seeded state (used before each case).

    Goes through app.ingest.process_report, the same single entry point the
    WhatsApp and web channels use, so the eval measures exactly that path.
    """
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"  # before app.models creates its engine
    sys.path.insert(0, str(ROOT / "backend"))
    from app import ingest, models, seed

    seed.seed()
    try:
        __import__(ingest.PROCESS_REPORT_MODULE, fromlist=["process_report"]).process_report
    except (ImportError, AttributeError) as exc:
        raise SystemExit(
            f"process_report is not available yet (expected in {ingest.PROCESS_REPORT_MODULE}, CIA-7). "
            f"Nothing was evaluated. ({exc})"
        ) from exc
    seeded = db_path.with_suffix(".seeded")
    models.engine.dispose()
    shutil.copyfile(db_path, seeded)

    def reset() -> None:
        models.engine.dispose()  # close pooled connections before swapping the file
        shutil.copyfile(seeded, db_path)

    return ingest.process_report, models, reset


def caregiver_for(models, patient_id: str) -> str:
    from sqlalchemy import select

    with models.SessionLocal() as s:
        person_id = s.scalar(
            select(models.PatientAccess.person_id).where(
                models.PatientAccess.patient_id == patient_id,
                models.PatientAccess.role == models.Role.caregiver,
            )
        )
    if person_id is None:
        raise LookupError(f"seed data has no caregiver for {patient_id}; fix the case or the seed")
    return person_id


def run(cases: list[Case], process_report, models, delay: float = 0.0,
        reset: Callable[[], None] | None = None) -> list[CaseScore]:
    run_id = uuid.uuid4().hex[:8]
    scores = []
    for n, case in enumerate(cases):
        if n and delay:
            time.sleep(delay)  # stay under the provider's tokens-per-minute limit
        if reset is not None:
            reset()
        start = time.perf_counter()
        try:
            # Positional on purpose: the sender parameter is being renamed
            # (caregiver_id -> sender_id, CIA-5); the order is the contract's.
            result = process_report(
                case.patient_id,
                caregiver_for(models, case.patient_id),
                case.transcript,
                None,
                f"eval-{run_id}-{case.case_id}",
            )
            score = score_case(case, result, time.perf_counter() - start)
        except Exception as exc:  # one broken case must not hide the others
            score = failed_score(case, time.perf_counter() - start, repr(exc))
        print(
            f"  {case.case_id} [{case.split}] {score.status} {score.seconds:.1f}s"
            + (f" FAILED {score.error}" if score.error else f" false_alarms={score.false_alarms}"),
            flush=True,
        )
        scores.append(score)
    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--split", choices=["all", "dev", "unseen"], default="all")
    parser.add_argument("--json", type=Path, help="write per-case scores to this file")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="seconds to wait between cases; ~30 keeps Groq's free tier (8,000 tokens/min) from rejecting calls")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    unseen = [c for c in cases if c.split == "unseen"]
    if len(unseen) < MIN_UNSEEN:
        print(f"WARNING: {len(unseen)} unseen cases; AGENTS.md section 11 asks for at least {MIN_UNSEEN}.")
    if args.split != "all":
        cases = [c for c in cases if c.split == args.split]
    if not cases:
        raise SystemExit(f"No cases for split '{args.split}' in {args.cases}.")

    with tempfile.TemporaryDirectory() as tmp:
        process_report, models, reset = prepare_backend(Path(tmp) / "eval.db")
        print(f"Running {len(cases)} cases through process_report...")
        scores = run(cases, process_report, models, delay=args.delay, reset=reset)

    print()
    for split in ("dev", "unseen"):
        subset = [s for s in scores if s.split == split]
        if subset:
            print(format_summary("Seen (dev)" if split == "dev" else "Unseen", summarize(subset)))
    print(format_summary("All", summarize(scores)))
    print("\nValues are not judged for wording; see the docstring for what each metric counts.")

    if args.json:
        args.json.write_text(json.dumps([asdict(s) | {"false_alarms": s.false_alarms} for s in scores], indent=2))
        print(f"Per-case results written to {args.json}")
    if any(s.error for s in scores):
        sys.exit(1)


if __name__ == "__main__":
    main()
