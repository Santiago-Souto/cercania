import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import ingest, web_reports
from app.deps import get_db
from app.main import app
from app.models import (
    Base,
    CarePlan,
    Medication,
    Patient,
    PatientAccess,
    Person,
    Report,
    Role,
)
from app.transcribe import Segment, Transcript, TranscriptionError

URL = "/patients/pat_x/reports"


@pytest.fixture(autouse=True)
def dev_identity(monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADER", "1")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Patient(id="pat_x", display_name="Rosa (ficticia)", vocabulary=["andador"]))
    session.add(CarePlan(id="plan_x", patient_id="pat_x", version=1))
    session.add(Medication(id="med_x", care_plan_id="plan_x", name="Enalapril", dose_text="1 comprimido", times=["08:00"]))
    for pid, role in [("cg", Role.caregiver), ("fam", Role.family), ("doc", Role.doctor)]:
        session.add(Person(id=pid, phone=f"+1555010000{len(pid)}{pid}", display_name=pid))
        session.add(PatientAccess(person_id=pid, patient_id="pat_x", role=role))
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.clear()
    session.close()


@pytest.fixture
def brain(monkeypatch):
    """Records calls instead of running Dev A's process_report."""
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return {"status": "ok", "report": {"id": "rep_1", "version": 1}}

    monkeypatch.setattr(ingest, "process_report", fake)
    return calls


@pytest.fixture
def groq(monkeypatch):
    calls = []

    def fake(audio, filename, mime_type, vocabulary):
        calls.append({"audio": audio, "filename": filename, "mime_type": mime_type, "vocabulary": vocabulary})
        return Transcript(text="comió poco en la cena", segments=[Segment(0.0, 1.8, "comió poco en la cena")])

    monkeypatch.setattr(web_reports, "transcribe", fake)
    return calls


client = TestClient(app)
AS_CAREGIVER = {"X-Person-Id": "cg"}


def test_text_report_goes_to_process_report(db, brain):
    r = client.post(URL, json={"client_id": "web_1", "text": "  durmió bien  "}, headers=AS_CAREGIVER)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert brain == [{
        "patient_id": "pat_x", "sender_id": "cg", "transcript": "durmió bien",
        "audio_ref": None, "message_id": "web:cg:web_1", "segments": [],
    }]


def test_audio_report_is_transcribed_with_patient_vocabulary(db, brain, groq):
    r = client.post(
        URL,
        data={"client_id": "web_2"},
        files={"audio": ("rec.webm", b"\x1aE\xdf\xa3", "audio/webm;codecs=opus")},
        headers=AS_CAREGIVER,
    )
    assert r.status_code == 200
    assert groq[0]["mime_type"] == "audio/webm"
    assert groq[0]["filename"] == "voice.webm"
    assert groq[0]["vocabulary"] == ["andador", "Enalapril"]
    assert brain[0]["transcript"] == "comió poco en la cena"
    assert brain[0]["message_id"] == "web:cg:web_2"
    assert brain[0]["segments"] == [{"start": 0.0, "end": 1.8, "text": "comió poco en la cena"}]


def test_repeated_client_id_reuses_stored_transcript_without_transcribing(db, brain, groq):
    db.add(Report(id="rep_1", patient_id="pat_x", sender_id="cg", message_id="web:cg:web_3", transcript="ya guardado"))
    db.commit()
    r = client.post(
        URL, data={"client_id": "web_3"}, files={"audio": ("rec.ogg", b"OggS", "audio/ogg")}, headers=AS_CAREGIVER
    )
    assert r.status_code == 200
    assert groq == []
    assert brain[0]["transcript"] == "ya guardado"
    assert brain[0]["message_id"] == "web:cg:web_3"


@pytest.mark.parametrize("person", ["fam", "doc"])
def test_only_roles_with_send_report_can_post(db, brain, person):
    r = client.post(URL, json={"client_id": "web_4", "text": "hola"}, headers={"X-Person-Id": person})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"
    assert brain == []


def test_person_without_access_gets_404_not_403(db, brain):
    """Like deps.patient_access: a stranger can't tell an existing patient from a missing one."""
    r = client.post(URL, json={"client_id": "web_4", "text": "hola"}, headers={"X-Person-Id": "stranger"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    assert brain == []


def test_missing_identity_is_401_in_contract_shape(db, brain):
    r = client.post(URL, json={"client_id": "web_5", "text": "hola"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_unknown_patient_is_404(db, brain):
    r = client.post("/patients/pat_nope/reports", json={"client_id": "w", "text": "hola"}, headers=AS_CAREGIVER)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "body, code",
    [
        ({"text": "hola"}, "client_id_missing"),
        ({"client_id": "  ", "text": "hola"}, "client_id_missing"),
        ({"client_id": "x" * 101, "text": "hola"}, "client_id_missing"),
        ({"client_id": "web_6", "text": "   "}, "text_missing"),
        ({"client_id": "web_6"}, "text_missing"),
    ],
)
def test_bad_json_bodies_get_clear_errors(db, brain, body, code):
    r = client.post(URL, json=body, headers=AS_CAREGIVER)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == code
    assert r.json()["error"]["message"]
    assert brain == []


def test_audio_errors(db, brain, groq):
    def post(files, data={"client_id": "web_7"}):
        return client.post(URL, data=data, files=files, headers=AS_CAREGIVER)

    assert post({"audio": ("a.png", b"x", "image/png")}).json()["error"]["code"] == "unsupported_audio"
    assert post({"audio": ("a.ogg", b"", "audio/ogg")}).json()["error"]["code"] == "audio_empty"
    assert client.post(URL, data={"client_id": "web_7"}, headers=AS_CAREGIVER).status_code in (400, 415)
    assert groq == [] and brain == []


def test_audio_too_large(db, brain, groq, monkeypatch):
    monkeypatch.setattr(web_reports, "MAX_AUDIO_BYTES", 3)
    r = client.post(URL, data={"client_id": "w8"}, files={"audio": ("a.ogg", b"OggS", "audio/ogg")}, headers=AS_CAREGIVER)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "audio_too_large"


def test_transcription_failure_returns_user_message(db, brain, monkeypatch):
    def fail(*a, **kw):
        raise TranscriptionError("groq 500", "No pude transcribir el audio.")

    monkeypatch.setattr(web_reports, "transcribe", fail)
    r = client.post(URL, data={"client_id": "w9"}, files={"audio": ("a.ogg", b"OggS", "audio/ogg")}, headers=AS_CAREGIVER)
    assert r.status_code == 502
    assert r.json()["error"] == {"code": "transcription_failed", "message": "No pude transcribir el audio."}
    assert brain == []


def test_unsupported_content_type(db, brain):
    r = client.post(URL, content=b"hola", headers={**AS_CAREGIVER, "Content-Type": "text/plain"})
    assert r.status_code == 415


def test_without_process_report_returns_503_not_a_fake_result(db, monkeypatch):
    monkeypatch.setattr(ingest, "PROCESS_REPORT_MODULE", "app.process_not_deployed")
    r = client.post(URL, json={"client_id": "w10", "text": "hola"}, headers=AS_CAREGIVER)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "processing_unavailable"


def test_client_id_of_another_user_never_reaches_their_report(db, brain):
    # Another caregiver's report stored with raw id "shared".
    db.add(Person(id="other", phone="+15550109998", display_name="other"))
    db.add(Patient(id="pat_y", display_name="Otro (ficticio)"))
    db.add(Report(id="rep_y", patient_id="pat_y", sender_id="other", message_id="web:other:shared",
                  transcript="datos de otro paciente"))
    db.commit()
    r = client.post(URL, json={"client_id": "shared", "text": "mi reporte"}, headers=AS_CAREGIVER)
    assert r.status_code == 200
    assert brain[0]["message_id"] == "web:cg:shared"
    assert brain[0]["transcript"] == "mi reporte"


def test_same_client_id_for_another_patient_is_a_conflict(db, brain):
    db.add(Patient(id="pat_z", display_name="Z (ficticio)"))
    db.add(Report(id="rep_z", patient_id="pat_z", sender_id="cg", message_id="web:cg:dup", transcript="de Z"))
    db.commit()
    r = client.post(URL, json={"client_id": "dup", "text": "hola"}, headers=AS_CAREGIVER)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "client_id_conflict"
    assert brain == []


def test_identity_header_is_ignored_unless_explicitly_enabled(db, brain, monkeypatch):
    monkeypatch.delenv("ALLOW_DEV_IDENTITY_HEADER")
    r = client.post(URL, json={"client_id": "w11", "text": "hola"}, headers=AS_CAREGIVER)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"
    assert brain == []
