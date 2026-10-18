"""process_report end to end with fake model clients (no network) on a seeded in-memory database."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import deps, extract, models, process, seed, triage
from app.models import (
    ChecklistItem,
    Report,
    ReportItem,
    ReportKind,
    ReportVersion,
    TriageStatus,
)

CG, FAM, DOC = "cg_001", "fam_001", "doc_001"
PAT = "pat_001"  # Rosa: enalapril 08:00 + 20:00 (med_001), metformina 08:00 (med_002)

@pytest.fixture(autouse=True)
def anthropic_models(monkeypatch):
    """The fake clients here mimic the Anthropic SDK; pin both tasks to that provider
    (extraction defaults to Groq, see llm.py)."""
    monkeypatch.setenv("EXTRACT_MODEL", "anthropic:test-model")
    monkeypatch.setenv("TRIAGE_MODEL", "anthropic:test-model")



@pytest.fixture(autouse=True)
def fake_extract_vendor(monkeypatch):
    """The fake clients mimic the Anthropic SDK; the default extraction vendor is Groq (llm.py)."""
    monkeypatch.setenv("EXTRACT_MODEL", "anthropic:test-model")


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    for module, attr, value in [(models, "engine", engine), (models, "SessionLocal", factory),
                                (seed, "engine", engine), (seed, "SessionLocal", factory),
                                (process, "SessionLocal", factory), (deps, "SessionLocal", factory)]:
        monkeypatch.setattr(module, attr, value)
    seed.seed()
    return factory


# --- fake Anthropic clients (tests only; shaped like test_extract / test_triage) -------------


class FakeClient:
    def __init__(self, payload=None, exc=None):
        self.calls = []
        text = json.dumps(payload) if payload is not None else "{}"
        self._response = SimpleNamespace(stop_reason="end_turn",
                                         content=[SimpleNamespace(type="text", text=text)])
        self._exc = exc
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._response


def triage_client(emergency=False, reason=None, quote=None):
    return FakeClient({"emergency": emergency, "reason": reason, "quote": quote})


def broken_triage():
    return FakeClient(exc=RuntimeError("boom"))


def extraction_payload(**given):
    """All items null, except those given as (value, level, quote) or a ready dict."""
    out = {}
    for item, levels in extract.ITEM_LEVELS.items():
        row = {"value": None, "quote": None}
        if levels is not None:
            row["level"] = None
        if item is ChecklistItem.medication:
            row["doses"] = []
        out[item.value] = row
    for name, spec in given.items():
        if isinstance(spec, dict):
            out[name].update(spec)
        else:
            value, level, quote = spec
            out[name].update(value=value, level=level, quote=quote)
    return out


def extract_client(**given):
    return FakeClient(extraction_payload(**given))


def extract_failing():
    import anthropic

    return FakeClient(exc=anthropic.APIConnectionError(request=None))


REPORT = "Rosa comió poco en la cena. Le di el enalapril a las ocho. Orinó bien. Sin caídas."


def happy_extract(quote="Le di el enalapril a las ocho"):
    return extract_client(
        appetite=("Comió poco en la cena", "low", "Rosa comió poco en la cena"),
        urination=("Normal", "normal", "Orinó bien"),
        incidents=("Sin caídas", "none", "Sin caídas"),
        medication={"value": "Enalapril 08:00", "quote": quote, "doses": [
            {"plan_ref": "med_001", "time": "08:00", "given": True, "quote": quote}]},
    )


def run(transcript, *, sender=CG, patient=PAT, message_id="wa-1", t=None, e=None):
    return process.process_report(
        patient_id=patient, sender_id=sender, transcript=transcript, audio_ref=None,
        message_id=message_id, triage_client=t or triage_client(), extract_client=e)


def rows(db, model):
    with db() as s:
        return s.scalar(select(func.count()).select_from(model))


def alerts_of(result, type_):
    return [a for a in result["alerts"] if a["type"] == type_]


# --- shift report ----------------------------------------------------------------------------


def test_shift_report_happy_path(db):
    n_before = rows(db, Report)
    r = run(REPORT, e=happy_extract())
    assert r["status"] == "ok" and r["red_flag"] is False
    assert r["report"]["version"] == 1 and r["triage"]["status"] == "ok"
    by_item = {i["item"]: i for i in r["items"]}
    assert len(r["items"]) == 8
    assert by_item["appetite"]["quote"] == "Rosa comió poco en la cena" and by_item["appetite"]["quote_verified"]
    assert by_item["medication"]["details"]["doses"][0]["plan_ref"] == "med_001"
    assert by_item["sleep"]["value"] is None
    assert r["missing_items"] == ["sleep", "mood", "mobility", "pain"]
    # alerts: missing items, unmentioned doses (med_001 20:00, med_002 08:00), change in appetite
    assert {a["item"] for a in alerts_of(r, "missing_item")} == set(r["missing_items"])
    omitted = {(a["plan_ref"], a["detail"]) for a in alerts_of(r, "omission")}
    assert omitted == {("med_001", "Enalapril 20:00: no se mencionó."),
                       ("med_002", "Metformina 08:00: no se mencionó.")}
    assert not alerts_of(r, "emergency")
    text = r["confirmation_text"]
    assert text.startswith("Registré: apetito: Comió poco en la cena;")
    assert "Metformina 08:00: no se mencionó." in text
    assert "No mencionaste: sueño, ánimo, movilidad, dolor. Podés mandar otra nota." in text
    assert triage.TRIAGE_FAILED_LINE not in text
    assert rows(db, Report) == n_before + 1
    with db() as s:
        report = s.get(Report, r["report"]["id"])
        assert report.kind == ReportKind.shift and report.channel == "whatsapp" and not report.red_flag
        assert report.latest.model == "anthropic:test-model" and report.latest.extraction_raw
        assert report.latest.created_by == CG and report.triage_status == TriageStatus.ok


def test_seed_history_produces_change_alert(db):
    r = run(REPORT, e=happy_extract())
    changes = alerts_of(r, "change")
    assert [a["item"] for a in changes] == ["appetite"]
    assert "3 turnos seguidos" in changes[0]["detail"]
    assert changes[0]["evidence_quote"] == "Rosa comió poco en la cena" and changes[0]["evidence_verified"]
    assert r["report"]["id"] in changes[0]["report_refs"] and "rep_001" in changes[0]["report_refs"]
    assert "Cambios:" in r["confirmation_text"]


def test_web_message_id_sets_channel(db):
    r = run(REPORT, message_id="web:cg_001:abc", e=happy_extract())
    with db() as s:
        assert s.get(Report, r["report"]["id"]).channel == "web"


def test_unverified_quote_never_produces_omission_or_change(db):
    bad = extract_client(
        appetite=("Comió poco", "low", "frase inventada que no está"),
        medication={"value": "Enalapril 08:00", "quote": "no le di nada", "doses": [
            {"plan_ref": "med_001", "time": "08:00", "given": False, "quote": "no le di el enalapril"}]},
    )
    r = run(REPORT, e=bad)
    assert r["status"] == "ok"
    by_item = {i["item"]: i for i in r["items"]}
    assert by_item["appetite"]["quote_verified"] is False
    assert alerts_of(r, "change") == []
    assert not [a for a in alerts_of(r, "omission") if "no se dio" in a["detail"]]
    unclear = [a for a in alerts_of(r, "omission") if a["plan_ref"] == "med_001" and "08:00" in a["detail"]]
    assert [a["detail"] for a in unclear] == ["Enalapril 08:00: no está claro."]
    assert unclear[0]["evidence_quote"] is None


def test_verified_not_given_dose_is_an_omission_with_evidence(db):
    text = "Hoy no le di el enalapril de las ocho. Sin caídas."
    e = extract_client(medication={"value": "No se dio enalapril 08:00", "quote": "no le di el enalapril de las ocho",
                                   "doses": [{"plan_ref": "med_001", "time": "08:00", "given": False,
                                              "quote": "no le di el enalapril de las ocho"}]})
    r = run(text, e=e)
    not_given = [a for a in alerts_of(r, "omission") if a["detail"].endswith("no se dio.")]
    assert len(not_given) == 1 and not_given[0]["evidence_verified"] is True
    assert not_given[0]["evidence_quote"] == "no le di el enalapril de las ocho"


# --- emergencies -----------------------------------------------------------------------------

FALL = "Rosa se cayó en el baño y se golpeó la cabeza, está sangrando"


def fall_triage():
    return triage_client(True, "Caída con golpe en la cabeza y sangrado", "se cayó en el baño y se golpeó la cabeza")


def test_caregiver_emergency_is_flagged_and_reply_is_fixed(db):
    r = run(FALL, t=fall_triage(), e=extract_client(incidents=("Caída con sangrado", "present", "Rosa se cayó en el baño")))
    assert r["status"] == "ok" and r["red_flag"] is True
    assert r["confirmation_text"] == triage.EMERGENCY_REPLY
    [alert] = alerts_of(r, "emergency")
    assert alert["detail"] == "Caída con golpe en la cabeza y sangrado"
    assert alert["evidence_quote"] == "se cayó en el baño y se golpeó la cabeza" and alert["evidence_verified"] is True
    assert alert["notifications"] == []
    assert r["triage"]["emergency"] is True
    assert len(r["items"]) == 8  # still a full shift report
    with db() as s:
        report = s.get(Report, r["report"]["id"])
        assert report.kind == ReportKind.shift and report.red_flag and report.triage_quote


def test_unverified_emergency_quote_still_stored_as_unverified(db):
    r = run(FALL, t=triage_client(True, "Caída", "frase que no está"), e=extract_client())
    [alert] = alerts_of(r, "emergency")
    assert alert["evidence_verified"] is False and r["red_flag"] is True


def test_emergency_survives_extraction_failure(db):
    r = run(FALL, t=fall_triage(), e=extract_failing())
    assert r["status"] == "ok" and r["red_flag"] is True
    assert r["items"] == [] and r["missing_items"] == []
    assert [a["type"] for a in r["alerts"]] == ["emergency"]
    assert r["confirmation_text"] == triage.EMERGENCY_REPLY
    with db() as s:
        report = s.get(Report, r["report"]["id"])
        assert report.kind == ReportKind.shift and report.latest.version == 1 and report.latest.items == []


def test_extraction_failure_without_emergency_stores_nothing(db):
    n = rows(db, Report)
    r = run(REPORT, e=extract_failing())
    assert r["status"] == "needs_retry" and r["red_flag"] is False and r["message"]
    assert r["triage"]["status"] == "ok" and r["triage"]["emergency"] is False
    assert triage.TRIAGE_FAILED_LINE not in r["message"]
    assert rows(db, Report) == n


def test_extraction_failure_and_triage_failure_adds_emergency_line(db):
    r = run(REPORT, t=broken_triage(), e=extract_failing())
    assert r["status"] == "needs_retry" and r["message"].endswith(triage.TRIAGE_FAILED_LINE)
    assert r["triage"]["status"] == "failed"


def test_triage_failed_still_stores_with_fixed_line(db):
    r = run(REPORT, t=broken_triage(), e=happy_extract())
    assert r["status"] == "ok" and r["red_flag"] is False
    assert r["triage"]["status"] == "failed"
    assert r["confirmation_text"].endswith("\n\n" + triage.TRIAGE_FAILED_LINE)
    assert r["confirmation_text"].startswith("Registré:")
    with db() as s:
        assert s.get(Report, r["report"]["id"]).triage_status == TriageStatus.failed


def test_non_caregiver_emergency_is_an_emergency_report_without_items(db):
    e = extract_client()
    r = run(FALL, sender=FAM, t=fall_triage(), e=e)
    assert r["status"] == "ok" and r["red_flag"] is True
    assert r["items"] == [] and r["missing_items"] == []
    assert [a["type"] for a in r["alerts"]] == ["emergency"]
    assert r["confirmation_text"] == triage.EMERGENCY_REPLY
    assert e.calls == []  # no extraction for non-caregivers
    with db() as s:
        report = s.get(Report, r["report"]["id"])
        assert report.kind == ReportKind.emergency and report.sender_id == FAM
        assert report.latest.items == []
        assert s.scalar(select(func.count()).select_from(ReportItem)
                        .where(ReportItem.report_version_id == report.latest.id)) == 0


def test_non_caregiver_without_emergency_stores_nothing(db):
    n = rows(db, Report)
    r = run("¿Cómo estuvo hoy?", sender=FAM, t=triage_client(False))
    assert r["status"] == "not_a_report" and r["red_flag"] is False and r["message"]
    assert r["triage"]["emergency"] is False
    assert rows(db, Report) == n


def test_unregistered_sender_is_forbidden_and_stores_nothing(db):
    n = rows(db, Report)
    t = triage_client()
    r = run(REPORT, sender="cg_002", t=t, e=happy_extract())  # caregiver of another patient only
    assert r["status"] == "forbidden" and r["message"]
    assert t.calls == [] and rows(db, Report) == n


# --- idempotency -----------------------------------------------------------------------------


def test_repeat_returns_identical_result_and_one_row(db):
    n = rows(db, Report)
    first = run(REPORT, message_id="wa-dup", e=happy_extract())
    t, e = triage_client(), happy_extract()
    second = run(REPORT, message_id="wa-dup", t=t, e=e)
    assert second == first
    assert t.calls == [] and e.calls == []  # no model calls on a repeat
    assert rows(db, Report) == n + 1


def test_race_on_message_id_returns_the_winner(db, monkeypatch):
    winner = run(REPORT, message_id="wa-race", e=happy_extract())
    real = process._existing
    calls = {"n": 0}

    def blind_first(session, message_id):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(session, message_id)

    monkeypatch.setattr(process, "_existing", blind_first)
    n = rows(db, Report)
    again = run(REPORT, message_id="wa-race", e=happy_extract())
    assert again == winner and rows(db, Report) == n


# --- transcript segments (docs/contract.md, "Transcript segments") ---------------------------

SEGMENTS = [
    {"start": 0.0, "end": 2.4, "text": "Rosa comió poco en la cena."},
    {"start": 2.4, "end": 4.9, "text": "Le di el enalapril"},
    {"start": 4.9, "end": 6.0, "text": "a las ocho. Orinó bien."},
    {"start": 6.0, "end": 7.1, "text": "Sin caídas."},
]


def test_segments_are_stored_and_give_items_audio_times(db):
    r = process.process_report(
        patient_id=PAT, sender_id=CG, transcript=REPORT, audio_ref=None, message_id="wa-seg",
        segments=SEGMENTS, triage_client=triage_client(), extract_client=happy_extract())
    by_item = {i["item"]: i for i in r["items"]}
    assert (by_item["appetite"]["audio_start_sec"], by_item["appetite"]["audio_end_sec"]) == (0.0, 2.4)
    # The quote spans two segments.
    assert (by_item["medication"]["audio_start_sec"], by_item["medication"]["audio_end_sec"]) == (2.4, 6.0)
    assert by_item["sleep"]["audio_start_sec"] is None  # not mentioned
    with db() as s:
        assert s.get(Report, r["report"]["id"]).segments == SEGMENTS


def test_unverified_quote_gets_no_audio_times(db):
    r = process.process_report(
        patient_id=PAT, sender_id=CG, transcript=REPORT, audio_ref=None, message_id="wa-seg2",
        segments=SEGMENTS, triage_client=triage_client(),
        extract_client=happy_extract(quote="le dio el enalapril"))
    med = next(i for i in r["items"] if i["item"] == "medication")
    assert med["quote_verified"] is False
    assert (med["audio_start_sec"], med["audio_end_sec"]) == (None, None)


def test_typed_report_has_no_segments_and_no_audio_times(db):
    r = run(REPORT, message_id="wa-typed", e=happy_extract())
    assert all(i["audio_start_sec"] is None for i in r["items"])
    with db() as s:
        assert s.get(Report, r["report"]["id"]).segments == []


def test_ingest_forwards_segments(monkeypatch):
    from app import ingest

    calls = []
    monkeypatch.setattr(process, "process_report", lambda **kw: calls.append(kw) or {"status": "ok"})
    ingest.process_report("pat", "cg", "t", None, "m1", segments=SEGMENTS)
    ingest.process_report("pat", "cg", "t", None, "m2")
    assert calls[0]["segments"] == SEGMENTS and calls[1]["segments"] == []
