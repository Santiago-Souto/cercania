"""Patient messages (CIA-29): "I need help" (fixed rule) and "how I feel" (triaged)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import notify, patient_messages, triage as triage_mod
from app.deps import get_db
from app.main import app
from app.models import (
    Base,
    Notification,
    NotificationChannel,
    NotificationStatus,
    Patient,
    PatientAccess,
    PatientMessage,
    Person,
    Role,
    TriageStatus,
)
from app.transcribe import Transcript, TranscriptionError

URL = "/patients/pat_x/patient-messages"
TEAM = {"cg", "cg2", "doc", "nur"}
client = TestClient(app)


def as_(person):
    return {"X-Person-Id": person}


@pytest.fixture(autouse=True)
def dev_identity(monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADER", "1")


@pytest.fixture
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    make = sessionmaker(bind=engine, expire_on_commit=False)
    with make() as s:
        s.add(Patient(id="pat_x", display_name="Rosa (ficticia)"))
        for i, (pid, role) in enumerate([("cg", Role.caregiver), ("cg2", Role.caregiver), ("doc", Role.doctor),
                                         ("nur", Role.nurse), ("fam", Role.family), ("ptl", Role.patient)]):
            s.add(Person(id=pid, phone=f"+1555030000{i}", display_name=pid.upper()))
            s.add(PatientAccess(person_id=pid, patient_id="pat_x", role=role))
        s.add(Person(id="other", phone="+15550309999", display_name="other"))
        s.commit()
    return make


@pytest.fixture
def db(factory):
    session = factory()
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.clear()
    session.close()


def fake_triage(monkeypatch, *, emergency=False, status=TriageStatus.ok, reason=None, quote=None):
    calls = []

    def fake(text, sender_role=None):
        calls.append((text, sender_role))
        return triage_mod.Triage(status=status, emergency=emergency, reason=reason, quote=quote,
                                 quote_verified=bool(quote), model="groq:test")

    monkeypatch.setattr(triage_mod, "triage", fake)
    return calls


def no_model(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("help must never call the model")

    monkeypatch.setattr(triage_mod, "triage", boom)
    monkeypatch.setattr(patient_messages, "transcribe", boom)


def web_rows(db, message_id):
    return db.scalars(select(Notification).where(Notification.patient_message_id == message_id,
                                                 Notification.channel == NotificationChannel.web.value)).all()


# --- help: fixed rule ------------------------------------------------------------------------


def test_help_notifies_every_caregiver_and_health_team_member_without_the_model(db, monkeypatch):
    no_model(monkeypatch)
    r = client.post(URL, json={"kind": "help"}, headers=as_("ptl"))
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "help" and body["red_flag"] is False
    assert set(body["notified"]) == TEAM  # never family, never the patient
    assert body["message_for_patient"] == "Ya avisamos a tu equipo. Si es una emergencia, llamá a emergencias."
    rows = web_rows(db, body["id"])
    assert {n.person_id for n in rows} == TEAM
    assert all(n.alert_id is None and n.report_id is None and n.status is NotificationStatus.sent for n in rows)
    assert rows[0].title == "Pedido de ayuda: Rosa (ficticia)"


def test_caregiver_testing_the_patient_view_is_not_notified_of_their_own_help(db, monkeypatch):
    no_model(monkeypatch)
    body = client.post(URL, json={"kind": "help"}, headers=as_("cg")).json()
    assert set(body["notified"]) == TEAM - {"cg"}


def test_help_reaches_the_team_inbox(db, monkeypatch):
    no_model(monkeypatch)
    pm = client.post(URL, json={"kind": "help"}, headers=as_("ptl")).json()
    inbox = client.get("/me/notifications", headers=as_("doc")).json()
    [n] = inbox["notifications"]
    assert n["patient_message_id"] == pm["id"] and n["alert_id"] is None and n["report_id"] is None
    assert inbox["unread_count"] == 1
    assert client.get("/me/notifications", headers=as_("fam")).json()["notifications"] == []


# --- feeling: triaged ------------------------------------------------------------------------


def test_feeling_without_emergency_still_notifies_the_team_as_not_urgent(db, monkeypatch):
    calls = fake_triage(monkeypatch)
    r = client.post(URL, json={"kind": "feeling", "text": "  me duele un poco la rodilla "}, headers=as_("ptl"))
    body = r.json()
    assert r.status_code == 200
    assert set(body["notified"]) == TEAM and body["red_flag"] is False  # CIA-60
    assert body["message_for_patient"] == patient_messages.FEELING_MESSAGE
    assert calls == [("me duele un poco la rodilla", Role.patient)]
    stored = db.get(PatientMessage, body["id"])
    assert stored.text == "me duele un poco la rodilla" and stored.triage_status is TriageStatus.ok
    rows = web_rows(db, body["id"])
    assert {n.person_id for n in rows} == TEAM
    assert rows[0].title == "Mensaje de Rosa (ficticia)" and "rodilla" not in rows[0].body  # no patient words
    [n] = client.get("/me/notifications", headers=as_("cg")).json()["notifications"]
    assert n["urgent"] is False
    assert client.get("/me/notifications", headers=as_("fam")).json()["notifications"] == []


def test_feeling_with_no_team_says_nobody_was_told(factory, monkeypatch):
    fake_triage(monkeypatch)
    session = factory()
    session.add(Patient(id="pat_alone", display_name="Solo (ficticio)"))
    session.add(PatientAccess(person_id="other", patient_id="pat_alone", role=Role.patient))
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        body = client.post("/patients/pat_alone/patient-messages", json={"kind": "feeling", "text": "bien"},
                           headers=as_("other")).json()
    finally:
        app.dependency_overrides.clear()
        session.close()
    assert body["notified"] == [] and body["message_for_patient"] == patient_messages.NO_TEAM_MESSAGE


def test_red_flag_feeling_notifies_the_team_with_fixed_text(db, monkeypatch):
    fake_triage(monkeypatch, emergency=True, reason="Dolor de pecho", quote="me duele el pecho")
    body = client.post(URL, json={"kind": "feeling", "text": "me duele el pecho y me falta el aire"},
                       headers=as_("ptl")).json()
    assert body["red_flag"] is True and set(body["notified"]) == TEAM
    assert body["message_for_patient"] == patient_messages.RED_FLAG_MESSAGE
    stored = db.get(PatientMessage, body["id"])
    assert (stored.triage_reason, stored.triage_quote, stored.triage_quote_verified) == (
        "Dolor de pecho", "me duele el pecho", True)
    rows = web_rows(db, body["id"])
    assert rows[0].title == "Posible emergencia: Rosa (ficticia)"
    assert "Motivo: Dolor de pecho." in rows[0].body and "falta el aire" not in rows[0].body  # no patient words


def test_failed_triage_still_tells_the_patient_to_call_emergencies(db, monkeypatch):
    fake_triage(monkeypatch, status=TriageStatus.failed)
    body = client.post(URL, json={"kind": "feeling", "text": "no me siento bien"}, headers=as_("ptl")).json()
    assert body["red_flag"] is False and set(body["notified"]) == TEAM
    assert triage_mod.TRIAGE_FAILED_LINE in body["message_for_patient"]
    assert db.get(PatientMessage, body["id"]).triage_status is TriageStatus.failed
    [n] = client.get("/me/notifications", headers=as_("cg")).json()["notifications"]
    assert n["urgent"] is True and n["title"] == "Revisá el mensaje de Rosa (ficticia)"


def test_feeling_audio_is_transcribed_then_triaged(db, monkeypatch):
    calls = fake_triage(monkeypatch)
    transcribed = []

    def fake_transcribe(data, filename, mime_type):
        transcribed.append((data, filename, mime_type))
        return Transcript(text="hoy me siento cansada")

    monkeypatch.setattr(patient_messages, "transcribe", fake_transcribe)
    r = client.post(URL, data={"kind": "feeling"}, files={"audio": ("a.webm", b"\x1aE", "audio/webm")},
                    headers=as_("ptl"))
    assert r.status_code == 200
    assert transcribed == [(b"\x1aE", "voice.webm", "audio/webm")]
    assert calls == [("hoy me siento cansada", Role.patient)]
    stored = db.get(PatientMessage, r.json()["id"])
    assert stored.from_audio is True and stored.text == "hoy me siento cansada"


def test_transcription_failure_asks_to_retry_and_mentions_emergencies(db, monkeypatch):
    fake_triage(monkeypatch)

    def fail(*a, **k):
        raise TranscriptionError("boom", "x")

    monkeypatch.setattr(patient_messages, "transcribe", fail)
    r = client.post(URL, data={"kind": "feeling"}, files={"audio": ("a.ogg", b"OggS", "audio/ogg")},
                    headers=as_("ptl"))
    assert r.status_code == 502
    error = r.json()["error"]
    assert error["code"] == "transcription_failed" and "llamá a emergencias" in error["message"]
    assert db.scalars(select(PatientMessage)).all() == []


@pytest.mark.parametrize("body, code", [
    ({"kind": "chat"}, "invalid_kind"),
    ({}, "invalid_kind"),
    ({"kind": "feeling"}, "text_missing"),
    ({"kind": "feeling", "text": "   "}, "text_missing"),
    ({"kind": "feeling", "text": "a" * 1001}, "text_too_long"),
])
def test_bad_bodies_get_clear_errors(db, monkeypatch, body, code):
    fake_triage(monkeypatch)
    r = client.post(URL, json=body, headers=as_("ptl"))
    assert r.status_code == 400 and r.json()["error"]["code"] == code


# --- access ----------------------------------------------------------------------------------


@pytest.mark.parametrize("person, status", [("fam", 403), ("doc", 403), ("nur", 403), ("other", 404)])
def test_only_patient_and_caregivers_can_post(db, monkeypatch, person, status):
    no_model(monkeypatch)
    assert client.post(URL, json={"kind": "help"}, headers=as_(person)).status_code == status


def test_unknown_patient_is_404(db):
    assert client.post("/patients/nope/patient-messages", json={"kind": "help"}, headers=as_("ptl")).status_code == 404


# --- list + seen_by --------------------------------------------------------------------------


def test_list_latest_first_and_team_reading_marks_seen(db, monkeypatch):
    fake_triage(monkeypatch)
    first = client.post(URL, json={"kind": "feeling", "text": "dormí bien"}, headers=as_("ptl")).json()["id"]
    second = client.post(URL, json={"kind": "help"}, headers=as_("ptl")).json()["id"]

    as_patient = client.get(URL, headers=as_("ptl")).json()["messages"]
    assert [m["id"] for m in as_patient] == [second, first]
    assert all(m["seen_by"] == [] for m in as_patient)  # the patient reading does not count as seen

    as_doctor = client.get(URL, headers=as_("doc")).json()["messages"]
    assert as_doctor[1] == {**as_doctor[1], "kind": "feeling", "text": "dormí bien", "red_flag": False,
                            "seen_by": [{"user_id": "doc", "name": "DOC"}]}
    client.get(URL, headers=as_("doc"))  # reading again adds nothing
    client.get(URL, headers=as_("nur"))
    again = client.get(URL, headers=as_("ptl")).json()["messages"]
    assert [s["user_id"] for s in again[0]["seen_by"]] == ["doc", "nur"]


def test_list_shows_the_triage_reason_only_on_red_flags(db, monkeypatch):
    fake_triage(monkeypatch, emergency=True, reason="Dolor de pecho", quote="me duele el pecho")
    client.post(URL, json={"kind": "feeling", "text": "me duele el pecho"}, headers=as_("ptl"))
    fake_triage(monkeypatch, reason="Nada grave")
    client.post(URL, json={"kind": "feeling", "text": "dormí bien"}, headers=as_("ptl"))
    calm, flagged = client.get(URL, headers=as_("cg")).json()["messages"]
    assert (flagged["red_flag"], flagged["reason"]) == (True, "Dolor de pecho")
    assert (calm["red_flag"], calm["reason"]) == (False, None)
    assert flagged["created_at"].endswith(("Z", "+00:00"))  # with an offset, or the browser reads it as local time


def test_family_cannot_read_patient_messages(db):
    assert client.get(URL, headers=as_("fam")).status_code == 403


def test_overlapping_polls_never_fail_on_seen(db, factory):
    """Two polls that both saw the message as unseen insert the same pair; the second is skipped."""
    with factory() as s:
        s.add(PatientMessage(id="pm_9", patient_id="pat_x", sender_id="ptl", kind="help"))
        s.commit()
    patient_messages.mark_seen(db, ["pm_9"], "doc")
    patient_messages.mark_seen(db, ["pm_9"], "doc")  # a plain insert would violate the unique pair here
    with factory() as s:
        assert [x.person_id for x in s.get(PatientMessage, "pm_9").seen] == ["doc"]
