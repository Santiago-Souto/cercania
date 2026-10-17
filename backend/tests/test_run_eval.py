import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))

import run_eval as ev  # noqa: E402

C001 = ev.Case(
    case_id="c001",
    patient_id="pat_001",
    transcript="hoy comio poco en la cena y se quejo de la rodilla",
    expected_items={"appetite", "pain"},
    expected_missing={"sleep", "urination", "mood", "mobility", "incidents", "medication"},
    expected_alerts={"omission:med_002"},
    split="dev",
)


def item(name, value=None, quote=None, verified=None):
    return {"item": name, "value": value, "quote": quote, "quote_verified": verified}


def test_perfect_result_scores_full_marks():
    result = {
        "status": "ok",
        "items": [
            item("appetite", "comió poco", "comio poco en la cena", True),
            item("pain", "rodilla", "se quejo de la rodilla", True),
        ],
        "missing_items": sorted(C001.expected_missing),
        "alerts": [{"type": "omission", "plan_ref": "med_002"}, {"type": "missing_item", "item": "sleep"}],
    }
    s = ev.score_case(C001, result)
    assert (s.fields_detected, s.fields_expected) == (2, 2)
    assert (s.missing_detected, s.missing_expected) == (6, 6)
    assert (s.omissions_detected, s.omissions_expected) == (1, 1)
    assert s.false_alarms == 0
    assert (s.quotes_verified, s.quotes) == (2, 2)


def test_every_kind_of_mistake_is_counted():
    result = {
        "status": "ok",
        "items": [
            item("appetite", "comió poco", "comio poco en la cena", True),
            item("pain", "rodilla", "inventado", False),        # unverified quote: not a detection
            item("sleep", "durmió bien", "durmio bien", False),  # invented: case says not mentioned
        ],
        "missing_items": ["urination", "pain"],                  # pain was mentioned
        "alerts": [{"type": "change", "item": "appetite"}],      # unexpected; omission missed
    }
    s = ev.score_case(C001, result)
    assert s.fields_detected == 1
    assert s.missing_detected == 1
    assert s.omissions_detected == 0
    assert s.unexpected_alerts == ["change:appetite"]
    assert s.invented_items == ["sleep"]
    assert s.wrongly_missing == ["pain"]
    assert s.false_alarms == 3
    assert (s.quotes_verified, s.quotes) == (1, 3)


def test_summary_separates_errors_and_formats_ratios():
    good = ev.score_case(C001, {"status": "ok", "items": [], "missing_items": [], "alerts": []}, seconds=2.0)
    broken = ev.CaseScore("c002", "unseen", "error", 0.1, error="boom")
    summary = ev.summarize([good, broken])
    assert summary["cases"] == 2 and summary["errors"] == 1
    assert summary["fields"] == (0, 2)
    text = ev.format_summary("All", summary)
    assert "1 errored" in text
    assert "Fields extracted (value + verified quote): 0/2 (0%)" in text
    assert "median 2.0s" in text


def test_ratio_without_cases():
    assert ev.ratio(0, 0) == "n/a (no cases)"


def test_repo_cases_file_parses():
    cases = ev.load_cases(ROOT / "eval" / "cases.csv")
    assert cases, "eval/cases.csv is empty"
    c001 = next(c for c in cases if c.case_id == "c001")
    assert c001.expected_items == {"appetite", "pain"}
    assert c001.expected_alerts == {"omission:med_002"}
    assert all(c.split in ("dev", "unseen") for c in cases)
