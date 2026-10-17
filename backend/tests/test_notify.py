"""Emergency dispatch: recipients, web inbox rows, best-effort WhatsApp, idempotency."""

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import ingest, notify, web_reports, whatsapp
from app.models import (
    Alert,
    AlertType,
    Base,
    Notification,
    NotificationChannel,
    NotificationStatus,
    Patient,
    PatientAccess,
    Person,
    Report,
    ReportVersion,
    Role,
    TriageStatus,
    VersionSource,
)
from app.whatsapp import IncomingMessage, SendResult
from app.transcribe import Transcript


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Patient(id="pat_x", display_name="Rosa (ficticia)",
                      health_provider_name="Centro ficticio", health_provider_phone="+15550300001"))
        people = [("cg", Role.caregiver), ("cg2", Role.caregiver), ("fam", Role.family),
                  ("doc", Role.doctor), ("pt", Role.patient)]
        for i, (pid, role) in enumerate(people):
            s.add(Person(id=pid, phone=f"+1555020000{i}", display_name=f"Persona {pid}"))
            s.add(PatientAccess(person_id=pid, patient_id="pat_x", role=role))
        s.add(Report(id="rep_1", patient_id="pat_x", sender_id="cg",
                     transcript="TRANSCRIPCION-SECRETA se cayó", red_flag=True,
                     triage_status=TriageStatus.ok, triage_reason="caída"))
        s.add(ReportVersion(id="rv_1", report_id="rep_1", version=1,
                            source=VersionSource.original, created_by="cg"))
        s.add(Alert(report_version_id="rv_1", type=AlertType.emergency, detail="caída"))
        s.commit()
    return eng


@pytest.fixture
def factory(engine):
    return lambda: Session(engine)


class FakeSender:
    def __init__(self, results=None, template_result=None):
        self.results = results or {}
        self.template_result = template_result or SendResult(True)
        self.texts, self.templates = [], []

    def send_text_result(self, to, text):
        self.texts.append((to, text))
        return self.results.get(to, SendResult(True))

    def send_template(self, to, name, lang):
        self.templates.append((to, name, lang))
        return self.template_result


def rows(engine):
    with Session(engine) as s:
        return s.scalars(select(Notification).order_by(Notification.channel, Notification.recipient,
                                                       Notification.person_id)).all()


def test_whatsapp_off_creates_web_rows_and_skipped_whatsapp_rows(engine, factory, monkeypatch):
    monkeypatch.setenv("NOTIFY_WHATSAPP", "0")
    sender = FakeSender()
    summary = notify.dispatch_emergency("rep_1", session_factory=factory, whatsapp_sender=sender)
    assert sender.texts == []
    got = rows(engine)
    web = [n for n in got if n.channel == NotificationChannel.web]
    wa = [n for n in got if n.channel == NotificationChannel.whatsapp]
    # sender, doctor and patient never notified
    assert {n.person_id for n in web} == {"cg2", "fam"}
    assert all(n.status == NotificationStatus.sent for n in web)
    assert {n.recipient for n in wa} == {"health_provider", "caregiver", "family"}
    assert all(n.status == NotificationStatus.skipped and "NOTIFY_WHATSAPP=0" in n.error for n in wa)
    # the health provider has no web inbox
    assert not [n for n in web if n.recipient == "health_provider"]
    assert len(summary) == 5


def test_message_text_has_no_transcript(engine, factory):
    notify.dispatch_emergency("rep_1", session_factory=factory, whatsapp_sender=FakeSender())
    n = rows(engine)[0]
    assert n.title == "Emergencia: Rosa (ficticia)"
    assert "Persona cg" in n.body and "caída" in n.body and "Abrí CercanIA" in n.body
    assert "SECRETA" not in n.body


def test_whatsapp_on_records_success_and_failure(engine, factory, monkeypatch):
    monkeypatch.setenv("NOTIFY_WHATSAPP", "1")
    sender = FakeSender(results={"15550200002": SendResult(False, 131030, "not in allowed list")})
    summary = notify.dispatch_emergency("rep_1", session_factory=factory, whatsapp_sender=sender)
    assert len(sender.texts) == 3  # provider, cg2, fam
    wa = {(s["to"], s["person_id"]): s for s in summary if s["channel"] == "whatsapp"}
    assert wa[("health_provider", None)]["status"] == "sent"
    assert wa[("caregiver", "cg2")]["status"] == "sent"
    failed = wa[("family", "fam")]
    assert failed["status"] == "failed" and "131030" in failed["error"]


def test_outside_window_falls_back_to_template(engine, factory, monkeypatch):
    monkeypatch.setenv("NOTIFY_WHATSAPP", "1")
    monkeypatch.setenv("WHATSAPP_EMERGENCY_TEMPLATE", "alerta_emergencia")
    sender = FakeSender(results={"15550300001": SendResult(False, whatsapp.OUTSIDE_WINDOW, "window")})
    summary = notify.dispatch_emergency("rep_1", session_factory=factory, whatsapp_sender=sender)
    assert sender.templates == [("15550300001", "alerta_emergencia", "es")]
    provider = next(s for s in summary if s["to"] == "health_provider")
    assert provider["status"] == "sent"


def test_outside_window_without_template_is_a_visible_failure(engine, factory, monkeypatch):
    monkeypatch.setenv("NOTIFY_WHATSAPP", "1")
    monkeypatch.delenv("WHATSAPP_EMERGENCY_TEMPLATE", raising=False)
    sender = FakeSender(results={"15550300001": SendResult(False, whatsapp.OUTSIDE_WINDOW, "window")})
    summary = notify.dispatch_emergency("rep_1", session_factory=factory, whatsapp_sender=sender)
    provider = next(s for s in summary if s["to"] == "health_provider")
    assert provider["status"] == "failed" and "plantilla" in provider["error"]
    assert sender.templates == []


def test_second_dispatch_sends_nothing(engine, factory, monkeypatch):
    monkeypatch.setenv("NOTIFY_WHATSAPP", "1")
    first = FakeSender()
    a = notify.dispatch_emergency("rep_1", session_factory=factory, whatsapp_sender=first)
    second = FakeSender()
    b = notify.dispatch_emergency("rep_1", session_factory=factory, whatsapp_sender=second)
    assert second.texts == [] and len(rows(engine)) == 5
    assert a == b


def test_alert_notifications_summary_is_persisted(engine, factory):
    summary = notify.dispatch_emergency("rep_1", session_factory=factory, whatsapp_sender=FakeSender())
    with Session(engine) as s:
        alert = s.scalars(select(Alert)).one()
        assert alert.notifications == summary
        assert set(summary[0]) == {"to", "person_id", "channel", "status", "error"}


def test_dispatch_never_raises(engine, factory):
    assert notify.dispatch_emergency("nope", session_factory=factory) == []

    def boom():
        raise RuntimeError("db down")

    assert notify.dispatch_emergency("rep_1", session_factory=boom) == []


def test_report_without_emergency_alert_returns_empty(engine, factory):
    with Session(engine) as s:
        s.add(Report(id="rep_2", patient_id="pat_x", sender_id="cg", transcript="todo bien"))
        s.add(ReportVersion(id="rv_2", report_id="rep_2", version=1, source=VersionSource.original, created_by="cg"))
        s.commit()
    assert notify.dispatch_emergency("rep_2", session_factory=factory) == []


# --- wiring -------------------------------------------------------------------------


def test_web_reports_schedules_dispatch_only_on_red_flag(monkeypatch):
    from fastapi.testclient import TestClient

    from app.deps import get_db
    from app.main import app

    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADER", "1")
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    session = Session(eng)
    session.add(Patient(id="pat_x", display_name="Rosa"))
    session.add(Person(id="cg", phone="+15550201", display_name="cg"))
    session.add(PatientAccess(person_id="cg", patient_id="pat_x", role=Role.caregiver))
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    dispatched = []
    monkeypatch.setattr(notify, "dispatch_emergency", lambda rid: dispatched.append(rid))
    outcome = {"red_flag": True}
    monkeypatch.setattr(ingest, "process_report",
                        lambda **kw: {"status": "ok", "report": {"id": "rep_9", "version": 1}, **outcome})
    try:
        client = TestClient(app)
        headers = {"X-Person-Id": "cg"}
        r = client.post("/patients/pat_x/reports", json={"client_id": "a", "text": "se cayó"}, headers=headers)
        assert r.status_code == 200 and dispatched == ["rep_9"]
        outcome["red_flag"] = False
        client.post("/patients/pat_x/reports", json={"client_id": "b", "text": "todo bien"}, headers=headers)
        assert dispatched == ["rep_9"]
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_whatsapp_deliver_dispatches_on_red_flag(monkeypatch):
    dispatched = []
    monkeypatch.setattr(notify, "dispatch_emergency", lambda rid: dispatched.append(rid))
    monkeypatch.setattr(whatsapp, "send_text", lambda to, text, client=None: True)
    result = {"status": "ok", "report": {"id": "rep_7", "version": 1}, "red_flag": True,
              "confirmation_text": "ok"}
    monkeypatch.setattr(ingest, "process_report", lambda **kw: dict(result))
    msg = IncomingMessage(id="w1", sender="1555", type="text", text="se cayó")
    whatsapp.deliver(msg, "cg", "pat_x", Transcript(text="se cayó"))
    assert dispatched == ["rep_7"]

    result["red_flag"] = False
    whatsapp.deliver(msg, "cg", "pat_x", Transcript(text="todo bien"))
    assert dispatched == ["rep_7"]


def test_whatsapp_deliver_survives_dispatch_crash(monkeypatch):
    sent = []

    def boom(rid):
        raise RuntimeError("x")

    monkeypatch.setattr(notify, "dispatch_emergency", boom)
    monkeypatch.setattr(whatsapp, "send_text", lambda to, text, client=None: sent.append(text) or True)
    monkeypatch.setattr(ingest, "process_report", lambda **kw: {
        "status": "ok", "report": {"id": "rep_7", "version": 1}, "red_flag": True, "confirmation_text": "ok"})
    whatsapp.deliver(IncomingMessage(id="w1", sender="1555", type="text", text="x"), "cg", "pat_x",
                     Transcript(text="x"))
    assert len(sent) == 1
