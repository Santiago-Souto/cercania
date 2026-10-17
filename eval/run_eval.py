"""Runs eval/cases.csv through the real process_report and prints the metrics
from AGENTS.md section 11, with seen (dev) and unseen cases separated.

    python eval/run_eval.py                  # all cases
    python eval/run_eval.py --split unseen   # only the held-out cases
    python eval/run_eval.py --json out.json  # also write per-case results

Each run uses a fresh temporary SQLite database with the fictional seed data,
so it never touches the team's database. Model calls are real (needs
ANTHROPIC_API_KEY); nothing here is simulated.

What "correct" means (scored by code, not by a model):
- field detected: an expected item came back with a value and a verified quote.
  The wording of the value is NOT judged (it is free text).
- missing item detected: an item the case says was not mentioned is in missing_items.
- omission detected: an expected `omission:<plan_ref>` alert came back.
- false alarm: an omission/change alert the case does not expect, an item reported
  although the case says it was not mentioned, or an item flagged missing although
  it was mentioned.
- quote verification pass rate: returned quotes that code verified against the transcript.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

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
    expected_alerts: set[str]  # "type:key", e.g. "omission:med_002"
    split: str


def _split_list(raw: str) -> list[str]:
    return [part.strip() for part in (raw or "").split(";") if part.strip()]


def load_cases(path: Path) -> list[Case]:
    with open(path, newline="", encoding="utf-8") as f:
        return [
            Case(
                case_id=row["case_id"],
                patient_id=row["patient_id"],
                transcript=row["transcript"],
                expected_items={entry.split("=", 1)[0].strip() for entry in _split_list(row["expected_items"])},
                expected_missing=set(_split_list(row["expected_missing_items"])),
                expected_alerts=set(_split_list(row["expected_alerts"])),
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
    unexpected_alerts: list[str] = field(default_factory=list)
    invented_items: list[str] = field(default_factory=list)  # reported but not mentioned
    wrongly_missing: list[str] = field(default_factory=list)  # flagged missing but mentioned
    quotes: int = 0
    quotes_verified: int = 0

    @property
    def false_alarms(self) -> int:
        return len(self.unexpected_alerts) + len(self.invented_items) + len(self.wrongly_missing)


def alert_key(alert: dict) -> str:
    return f"{alert.get('type')}:{alert.get('plan_ref') or alert.get('item') or ''}"


def score_case(case: Case, result: dict, seconds: float = 0.0) -> CaseScore:
    items = result.get("items") or []
    detected = {i["item"] for i in items if i.get("value") is not None and i.get("quote_verified")}
    reported = {i["item"] for i in items if i.get("value") is not None}
    missing = set(result.get("missing_items") or [])
    alerts = {alert_key(a) for a in result.get("alerts") or [] if a.get("type") in ("omission", "change")}
    expected_omissions = {a for a in case.expected_alerts if a.startswith("omission:")}
    quoted = [i for i in items if i.get("quote")]

    return CaseScore(
        case_id=case.case_id,
        split=case.split,
        status=result.get("status", "missing_status"),
        seconds=seconds,
        fields_expected=len(case.expected_items),
        fields_detected=len(case.expected_items & detected),
        missing_expected=len(case.expected_missing),
        missing_detected=len(case.expected_missing & missing),
        omissions_expected=len(expected_omissions),
        omissions_detected=len(expected_omissions & alerts),
        unexpected_alerts=sorted(alerts - case.expected_alerts),
        invented_items=sorted(reported & case.expected_missing),
        wrongly_missing=sorted(missing & case.expected_items),
        quotes=len(quoted),
        quotes_verified=sum(1 for i in quoted if i.get("quote_verified") is True),
    )


def ratio(num: int, den: int) -> str:
    return f"{num}/{den} ({100 * num / den:.0f}%)" if den else "n/a (no cases)"


def summarize(scores: list[CaseScore]) -> dict:
    ok = [s for s in scores if s.error is None]
    times = [s.seconds for s in ok]
    return {
        "cases": len(scores),
        "errors": len(scores) - len(ok),
        "fields": (sum(s.fields_detected for s in ok), sum(s.fields_expected for s in ok)),
        "omissions": (sum(s.omissions_detected for s in ok), sum(s.omissions_expected for s in ok)),
        "missing": (sum(s.missing_detected for s in ok), sum(s.missing_expected for s in ok)),
        "false_alarms": sum(s.false_alarms for s in ok),
        "quotes": (sum(s.quotes_verified for s in ok), sum(s.quotes for s in ok)),
        "median_s": statistics.median(times) if times else None,
        "max_s": max(times) if times else None,
    }


def format_summary(title: str, summary: dict) -> str:
    lines = [f"== {title}: {summary['cases']} cases" + (f", {summary['errors']} errored" if summary["errors"] else "")]
    if summary["cases"] == summary["errors"]:
        return "\n".join(lines + ["   (nothing to score)"])
    lines += [
        f"   Fields extracted (value + verified quote): {ratio(*summary['fields'])}",
        f"   Omissions detected:                        {ratio(*summary['omissions'])}",
        f"   Missing items detected:                    {ratio(*summary['missing'])}",
        f"   False alarms:                              {summary['false_alarms']}",
        f"   Quote verification pass rate:              {ratio(*summary['quotes'])}",
        f"   Latency per report: median {summary['median_s']:.1f}s, max {summary['max_s']:.1f}s",
    ]
    return "\n".join(lines)


# --- Running against the real pipeline -----------------------------------------------


def prepare_backend(db_path: Path):
    """Points the backend at a fresh SQLite file, seeds it, returns (process_report, models)."""
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"  # before app.models creates its engine
    sys.path.insert(0, str(ROOT / "backend"))
    from app import models, seed

    seed.seed()
    try:
        from app.process import process_report
    except ImportError as exc:
        raise SystemExit(
            "process_report is not available yet (expected in backend/app/process.py, CIA-7). "
            f"Nothing was evaluated. ({exc})"
        ) from exc
    return process_report, models


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
        raise SystemExit(f"Seed data has no caregiver for {patient_id}; fix the case or the seed.")
    return person_id


def run(cases: list[Case], process_report, models) -> list[CaseScore]:
    run_id = uuid.uuid4().hex[:8]
    scores = []
    for case in cases:
        start = time.perf_counter()
        try:
            result = process_report(
                patient_id=case.patient_id,
                caregiver_id=caregiver_for(models, case.patient_id),
                transcript=case.transcript,
                audio_ref=None,
                message_id=f"eval-{run_id}-{case.case_id}",
            )
            score = score_case(case, result, time.perf_counter() - start)
        except Exception as exc:  # one broken case must not hide the others
            score = CaseScore(case.case_id, case.split, "error", time.perf_counter() - start, error=repr(exc))
        print(
            f"  {case.case_id} [{case.split}] {score.status} {score.seconds:.1f}s"
            + (f" ERROR {score.error}" if score.error else f" false_alarms={score.false_alarms}"),
            flush=True,
        )
        scores.append(score)
    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--split", choices=["all", "dev", "unseen"], default="all")
    parser.add_argument("--json", type=Path, help="write per-case scores to this file")
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
        process_report, models = prepare_backend(Path(tmp) / "eval.db")
        print(f"Running {len(cases)} cases through process_report...")
        scores = run(cases, process_report, models)

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
