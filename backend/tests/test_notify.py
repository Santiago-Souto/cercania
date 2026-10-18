"""Emergency dispatch: recipients, web inbox rows, idempotency."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import ingest, notify
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


def rows(engine):
    with Session(engine) as s:
        return s.scalars(select(Notification).order_by(Notification.channel, Notification.recipient,
                                                       Notification.person_id)).all()


def test_dispatch_creates_one_web_inbox_row_per_caregiver_and_family(engine, factory):
    summary = notify.dispatch_emergency("rep_1", session_factory=factory)
    got = rows(engine)
    # sender, doctor, patient and the health provider contact (no inbox) are never notified
    assert {n.person_id for n in got} == {"cg2", "fam"}
    assert all(n.channel == NotificationChannel.web.value and n.status == NotificationStatus.sent for n in got)
    assert {n.recipient for n in got} == {"caregiver", "family"}
    assert len(summary) == 2 and all(s["channel"] == "web" for s in summary)


def test_message_text_has_no_transcript(engine, factory):
    notify.dispatch_emergency("rep_1", session_factory=factory)
    n = rows(engine)[0]
    assert n.title == "Emergencia: Rosa (ficticia)"
    assert "Persona cg" in n.body and "caída" in n.body and "Abrí CercanIA" in n.body
    assert "SECRETA" not in n.body


def test_second_dispatch_notifies_nobody_again(engine, factory):
    a = notify.dispatch_emergency("rep_1", session_factory=factory)
    b = notify.dispatch_emergency("rep_1", session_factory=factory)
    assert len(rows(engine)) == 2
    assert a == b


def test_retry_after_partial_dispatch_adds_only_the_missing_rows(engine, factory):
    notify.dispatch_emergency("rep_1", session_factory=factory)
    with Session(engine) as s:  # simulate a dispatch that died before the family row was stored
        s.delete(s.scalars(select(Notification).where(Notification.person_id == "fam")).one())
        s.commit()
    summary = notify.dispatch_emergency("rep_1", session_factory=factory)
    assert len(rows(engine)) == 2
    assert sorted(x["person_id"] for x in summary) == ["cg2", "fam"]


def test_alert_notifications_summary_is_persisted(engine, factory):
    summary = notify.dispatch_emergency("rep_1", session_factory=factory)
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
