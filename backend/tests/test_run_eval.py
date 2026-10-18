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


def test_failed_case_stays_in_every_denominator():
    good = ev.score_case(C001, {
        "status": "ok",
        "items": [item("appetite", "poco", "comio poco", True), item("pain", "rodilla", "rodilla", True)],
        "missing_items": [], "alerts": [{"type": "omission", "plan_ref": "med_002"}],
    }, seconds=2.0)
    broken = ev.failed_score(C001, 4.0, "boom")
    summary = ev.summarize([good, broken])
    assert summary["cases"] == 2 and summary["errors"] == 1
    assert summary["fields"] == (2, 4)       # not 2/2
    assert summary["omissions"] == (1, 2)
    assert summary["max_s"] == 4.0           # failed time counts too
    text = ev.format_summary("All", summary)
    assert "1 FAILED (counted as zero detections)" in text
    assert "Fields extracted (value + verified quote): 2/4 (50%)" in text


def test_non_ok_status_is_a_failed_case():
    s = ev.score_case(C001, {"status": "needs_retry", "message": "modelo caído", "items": []})
    assert s.error and "needs_retry" in s.error and "modelo caído" in s.error
    assert s.status == "needs_retry"
    assert (s.fields_detected, s.fields_expected) == (0, 2)
    assert s.omissions_expected == 1


def test_change_alerts_are_scored_by_item():
    case = ev.Case("c9", "pat_001", "...", set(), set(), {"change:appetite"}, "dev")
    hit = ev.score_case(case, {"status": "ok", "items": [], "missing_items": [],
                               "alerts": [{"type": "change", "item": "appetite", "report_refs": ["r1"]}]})
    assert (hit.changes_detected, hit.changes_expected) == (1, 1)
    assert hit.false_alarms == 0
    miss = ev.score_case(case, {"status": "ok", "items": [], "missing_items": [],
                                "alerts": [{"type": "change", "item": "sleep"}]})
    assert miss.changes_detected == 0
    assert miss.unexpected_alerts == ["change:sleep"]


def test_bad_patient_id_fails_one_case_not_the_run(monkeypatch):
    other = ev.Case("c002", "pat_002", "durmio bien", {"sleep"}, set(), set(), "unseen")
    ok_result = {"status": "ok", "items": [item("sleep", "bien", "durmio bien", True)], "missing_items": [], "alerts": []}

    calls = iter([LookupError, ok_result])

    def caregiver(models, patient_id):
        outcome = next(calls)
        if outcome is LookupError:
            raise LookupError("no caregiver")
        return "cg"

    monkeypatch.setattr(ev, "caregiver_for", caregiver)
    scores = ev.run([C001, other], lambda *args: ok_result, models=None)
    assert [s.case_id for s in scores] == ["c001", "c002"]
    assert scores[0].error and "no caregiver" in scores[0].error
    assert scores[1].error is None and scores[1].fields_detected == 1


def test_ratio_without_cases():
    assert ev.ratio(0, 0) == "n/a (no cases)"


def test_repo_cases_file_parses():
    cases = ev.load_cases(ROOT / "eval" / "cases.csv")
    assert cases, "eval/cases.csv is empty"
    c001 = next(c for c in cases if c.case_id == "c001")
    assert c001.expected_items == {"appetite", "pain"}
    assert c001.expected_alerts == {"omission:med_002"}
    assert all(c.split in ("dev", "unseen") for c in cases)


C003 = ev.Case(
    case_id="c003",
    patient_id="pat_002",
    transcript="jorge se fue al piso en el pasillo y no se puede levantar, le sangra la cabeza",
    expected_items={"incidents", "mobility"},
    expected_missing=set(),
    expected_alerts={"emergency:"},
    split="dev",
)


def emergency_alert():
    return {"type": "emergency", "item": None, "plan_ref": None, "detail": "caída con sangrado"}


def test_emergency_detected_when_expected():
    s = ev.score_case(C003, {"status": "ok", "items": [], "missing_items": [], "alerts": [emergency_alert()]})
    assert (s.emergencies_detected, s.emergencies_expected) == (1, 1)
    assert s.emergency_false_alarms == 0
    assert "emergency:" not in s.unexpected_alerts


def test_missed_emergency_counts_against_recall():
    s = ev.score_case(C003, {"status": "ok", "items": [], "missing_items": [], "alerts": []})
    assert (s.emergencies_detected, s.emergencies_expected) == (0, 1)


def test_emergency_on_a_calm_report_is_an_emergency_false_alarm():
    s = ev.score_case(C001, {"status": "ok", "items": [], "missing_items": [],
                             "alerts": [{"type": "omission", "plan_ref": "med_002"}, emergency_alert()]})
    assert s.emergencies_expected == 0
    assert s.emergency_false_alarms == 1
    assert s.unexpected_alerts == ["emergency:"]
    assert s.false_alarms == 1


def test_failed_case_keeps_its_expected_emergency():
    assert ev.failed_score(C003, 1.0, "boom").emergencies_expected == 1


def test_summary_prints_emergency_lines():
    hit = ev.score_case(C003, {"status": "ok", "items": [], "missing_items": [], "alerts": [emergency_alert()]})
    false_alarm = ev.score_case(C001, {"status": "ok", "items": [], "missing_items": [], "alerts": [emergency_alert()]})
    text = ev.format_summary("All", ev.summarize([hit, false_alarm]))
    assert "Emergencies detected:                      1/1 (100%)" in text
    assert "Emergency false alarms:                    1" in text


def test_repo_emergency_case_parses_as_expected_emergency():
    cases = {c.case_id: c for c in ev.load_cases(ROOT / "eval" / "cases.csv")}
    assert "emergency:" in cases["c003"].expected_alerts
