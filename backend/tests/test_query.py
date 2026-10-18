import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import query as query_mod
from app.deps import get_db
from app.main import app
from app.models import (
    Base,
    Patient,
    PatientAccess,
    PatientMessage,
    PatientMessageKind,
    PatientMessageSeen,
    Person,
    Report,
    ReportKind,
    Role,
)

URL = "/patients/pat_x/query"
TRANSCRIPT = "Anoche le di la medicación de las ocho. Comió poco en la cena. Durmió bien."
SEGMENTS = [
    {"start": 0.0, "end": 3.5, "text": "Anoche le di la medicación de las ocho."},
    {"start": 3.5, "end": 6.0, "text": "Comió poco en la cena."},
    {"start": 6.0, "end": 8.0, "text": "Durmió bien."},
]
BODY = {"question": "¿Tomó la medicación de la noche ayer?"}
AS_CAREGIVER = {"X-Person-Id": "cg"}


class FakeClient:
    def __init__(self, payload: dict | str | None = None, error: Exception | None = None):
        self.calls = []
        self.error = error
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self._response = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self._response


def model_reply(citations, confidence="answered", note=None):
    return {"answer": "Sí, se le dio la medicación de las ocho.", "confidence": confidence,
            "citations": citations, "note": note}


@pytest.fixture(autouse=True)
def dev_identity(monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADER", "1")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Patient(id="pat_x", display_name="Rosa (ficticia)"))
    session.add(Patient(id="pat_y", display_name="Otro (ficticio)"))
    for pid, role in [("cg", Role.caregiver), ("fam", Role.family), ("pt", Role.patient), ("nur", Role.nurse)]:
        session.add(Person(id=pid, phone=f"+1555020000{pid}", display_name=pid))
        session.add(PatientAccess(person_id=pid, patient_id="pat_x", role=role))
    session.add(Person(id="out", phone="+1555020000out", display_name="out"))
    session.add(PatientAccess(person_id="out", patient_id="pat_y", role=Role.caregiver))
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.clear()
    session.close()


@pytest.fixture
def report(db):
    r = Report(id="rep_1", patient_id="pat_x", sender_id="cg", kind=ReportKind.shift,
               transcript=TRANSCRIPT, segments=SEGMENTS)
    db.add(r)
    db.commit()
    return r


# The fake below speaks the Anthropic SDK interface; the query logic under test is the
# same for every provider, so these tests pin an Anthropic model instead of the default.
FAKE_MODEL = "anthropic:claude-sonnet-5-5"


@pytest.fixture
def fake(monkeypatch):
    """Install a fake client; tests set `holder['client']`."""
    holder = {}
    monkeypatch.setenv("QUERY_MODEL", FAKE_MODEL)
    monkeypatch.setattr(query_mod, "_default_client", lambda: holder["client"])
    return holder


client = TestClient(app)


def test_answered_with_verified_citation(db, report, fake):
    fake["client"] = FakeClient(model_reply([{"source_id": "rep_1", "quote": "le di la medicación de las ocho"}]))
    r = client.post(URL, json=BODY, headers=AS_CAREGIVER)
    assert r.status_code == 200
    body = r.json()
    assert body["confidence"] == "answered"
    [cit] = body["citations"]
    assert cit.pop("created_at")  # when the report was received
    assert cit == {"source": "report", "report_id": "rep_1", "patient_message_id": None,
                   "quote": "le di la medicación de las ocho", "audio_start_sec": 0.0, "audio_end_sec": 3.5}
    call = fake["client"].calls[0]
    assert call["model"] == query_mod.llm.parse_model(FAKE_MODEL)[1]  # llm.py drops the provider prefix
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert 'id="rep_1"' in call["messages"][0]["content"]


def test_invented_quote_is_dropped_and_real_one_kept(db, report, fake):
    fake["client"] = FakeClient(model_reply([
        {"source_id": "rep_1", "quote": "se negó a tomar la medicación"},
        {"source_id": "rep_1", "quote": "Comió poco en la cena"},
    ]))
    body = client.post(URL, json=BODY, headers=AS_CAREGIVER).json()
    assert [c["quote"] for c in body["citations"]] == ["Comió poco en la cena"]
    assert body["confidence"] == "answered"


def test_unknown_report_id_is_dropped(db, report, fake):
    fake["client"] = FakeClient(model_reply([
        {"source_id": "rep_999", "quote": "Comió poco en la cena"},
        {"source_id": "rep_1", "quote": "Durmió bien"},
    ]))
    body = client.post(URL, json=BODY, headers=AS_CAREGIVER).json()
    assert [c["report_id"] for c in body["citations"]] == ["rep_1"]


def test_answered_without_surviving_citations_becomes_unclear(db, report, fake):
    fake["client"] = FakeClient(model_reply([{"source_id": "rep_1", "quote": "tomó todo sin problemas"}]))
    body = client.post(URL, json=BODY, headers=AS_CAREGIVER).json()
    assert body["confidence"] == "unclear"
    assert body["citations"] == []
    assert body["note"] == query_mod.UNVERIFIED_NOTE


def test_unclear_reply_passes_through_with_note(db, report, fake):
    fake["client"] = FakeClient(model_reply([], confidence="unclear", note="Falta el reporte de ayer."))
    body = client.post(URL, json=BODY, headers=AS_CAREGIVER).json()
    assert body["confidence"] == "unclear"
    assert body["note"] == "Falta el reporte de ayer."


def test_segment_timing_from_the_segments_that_contain_the_quote():
    reports = [{"id": "rep_1", "transcript": TRANSCRIPT, "segments": SEGMENTS}]
    one = query_mod.verify_citations([{"source_id": "rep_1", "quote": "comió poco en la cena"}], reports)
    assert (one[0]["audio_start_sec"], one[0]["audio_end_sec"]) == (3.5, 6.0)
    # Spans two segments: from the first one's start to the second one's end.
    two = query_mod.verify_citations([{"source_id": "rep_1", "quote": "las ocho. Comió poco"}], reports)
    assert (two[0]["audio_start_sec"], two[0]["audio_end_sec"]) == (0.0, 6.0)
    # No segments stored (text report).
    none = query_mod.verify_citations(
        [{"source_id": "rep_1", "quote": "Durmió bien"}], [{"id": "rep_1", "transcript": TRANSCRIPT, "segments": []}]
    )
    assert none[0]["audio_start_sec"] is None


def test_model_error_returns_502_query_failed(db, report, fake):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    fake["client"] = FakeClient(error=anthropic.APIConnectionError(request=request))
    r = client.post(URL, json=BODY, headers=AS_CAREGIVER)
    assert r.status_code == 502
    err = r.json()["error"]
    assert err["code"] == "query_failed"
    assert "IA" in err["message"]


def test_malformed_model_output_returns_502(db, report, fake):
    fake["client"] = FakeClient("not json")
    r = client.post(URL, json=BODY, headers=AS_CAREGIVER)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "query_failed"


def test_no_reports_is_unclear_without_calling_the_model(db, fake):
    fake["client"] = FakeClient(model_reply([]))
    r = client.post(URL, json=BODY, headers=AS_CAREGIVER)
    assert r.status_code == 200
    assert r.json() == {"answer": "Todavía no hay reportes para este paciente.", "citations": [],
                        "confidence": "unclear", "note": None}
    assert fake["client"].calls == []


def test_family_can_query(db, report, fake):
    fake["client"] = FakeClient(model_reply([{"source_id": "rep_1", "quote": "Durmió bien"}]))
    assert client.post(URL, json=BODY, headers={"X-Person-Id": "fam"}).status_code == 200


def test_patient_role_is_forbidden(db, report, fake):
    fake["client"] = FakeClient(model_reply([]))
    r = client.post(URL, json=BODY, headers={"X-Person-Id": "pt"})
    assert r.status_code == 403
    assert fake["client"].calls == []


def test_outsider_gets_404(db, report, fake):
    fake["client"] = FakeClient(model_reply([]))
    r = client.post(URL, json=BODY, headers={"X-Person-Id": "out"})
    assert r.status_code == 404
    assert fake["client"].calls == []


@pytest.mark.parametrize("body", [{"question": ""}, {"question": "   "}, {}, {"question": "x" * 501}])
def test_invalid_question_is_422(db, report, fake, body):
    r = client.post(URL, json=body, headers=AS_CAREGIVER)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"


def test_default_query_model_is_groq():
    # No Anthropic key is configured on Render; the query shares Groq with extraction.
    assert query_mod.DEFAULT_MODEL == "groq:openai/gpt-oss-120b"


# --- the patient's own messages (CIA-62) -----------------------------------------------------

FEELING = "Hoy me duele mucho la rodilla y casi no dormí."


@pytest.fixture
def feeling(db):
    db.add(PatientMessage(id="pm_1", patient_id="pat_x", sender_id="pt", kind=PatientMessageKind.feeling, text=FEELING))
    db.add(PatientMessage(id="pm_help", patient_id="pat_x", sender_id="pt", kind=PatientMessageKind.help))
    db.commit()


@pytest.mark.parametrize("asker", ["cg", "nur"])
def test_team_answers_read_and_cite_what_the_patient_said(db, report, feeling, fake, asker):
    fake["client"] = FakeClient(model_reply([
        {"source_id": "pm_1", "quote": "me duele mucho la rodilla"},
        {"source_id": "pm_1", "quote": "me caí en el baño"},  # not in the message: dropped
        {"source_id": "rep_1", "quote": "Durmió bien"},
    ]))
    body = client.post(URL, json={"question": "¿Cómo dice que se siente?"}, headers={"X-Person-Id": asker}).json()
    prompt = fake["client"].calls[0]["messages"][0]["content"]
    assert '<patient_message id="pm_1">' in prompt and FEELING in prompt
    assert "pm_help" not in prompt  # help requests have no words to quote
    by_source = {c["source"]: c for c in body["citations"]}
    assert len(body["citations"]) == 2
    assert by_source["patient_message"]["patient_message_id"] == "pm_1"
    assert by_source["patient_message"]["report_id"] is None
    assert by_source["patient_message"]["audio_start_sec"] is None and by_source["patient_message"]["created_at"]
    assert by_source["report"]["report_id"] == "rep_1"
    assert db.query(PatientMessageSeen).count() == 0  # asking does not mark them seen


def test_family_never_gets_the_patients_messages(db, report, feeling, fake):
    """Family may query but not read patient messages: they are not sent, and cannot be cited."""
    fake["client"] = FakeClient(model_reply([
        {"source_id": "pm_1", "quote": "me duele mucho la rodilla"},
        {"source_id": "rep_1", "quote": "Durmió bien"},
    ]))
    body = client.post(URL, json=BODY, headers={"X-Person-Id": "fam"}).json()
    prompt = fake["client"].calls[0]["messages"][0]["content"]
    assert "pm_1" not in prompt and FEELING not in prompt and "<patient_message" not in prompt
    assert [c["source"] for c in body["citations"]] == ["report"]


def test_only_patient_messages_still_calls_the_model(db, feeling, fake):
    fake["client"] = FakeClient(model_reply([{"source_id": "pm_1", "quote": "casi no dormí"}]))
    body = client.post(URL, json=BODY, headers=AS_CAREGIVER).json()
    assert len(fake["client"].calls) == 1
    assert body["confidence"] == "answered" and body["citations"][0]["patient_message_id"] == "pm_1"
    # Family has nothing it may read: no model call.
    fake["client"] = FakeClient(model_reply([]))
    body = client.post(URL, json=BODY, headers={"X-Person-Id": "fam"}).json()
    assert body["confidence"] == "unclear" and fake["client"].calls == []
