from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.deps import get_db
from app.main import app
from app.models import (
    Alert,
    AlertType,
    Base,
    Notification,
    NotificationChannel,
    NotificationStatus,
    Patient,
    Person,
    Report,
    ReportVersion,
    VersionSource,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def dev_identity(monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADER", "1")


@pytest.fixture
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(Patient(id="pat_x", display_name="Rosa (ficticia)"))
    for pid in ("fam", "other", "cg"):
        s.add(Person(id=pid, phone=f"+1555040{pid}", display_name=pid))
    s.add(Report(id="rep_1", patient_id="pat_x", sender_id="cg", transcript="t", red_flag=True))
    s.add(ReportVersion(id="rv_1", report_id="rep_1", version=1, source=VersionSource.original, created_by="cg"))
    for i in range(1, 6):  # one alert per row: (alert, recipient, person, channel) is unique
        s.add(Alert(id=i, report_version_id="rv_1", type=AlertType.emergency, detail="caída"))

    def add(nid, person, minutes, channel=NotificationChannel.web.value, read=False):
        s.add(Notification(id=nid, alert_id=int(nid[1]), report_id="rep_1", patient_id="pat_x", person_id=person,
                           recipient="family", channel=channel, status=NotificationStatus.sent,
                           title="Emergencia: Rosa (ficticia)", body="b",
                           created_at=NOW + timedelta(minutes=minutes),
                           read_at=NOW if read else None))

    add("n1", "fam", 0)
    add("n2", "fam", 10)
    add("n3", "fam", 20, read=True)
    add("n4", "fam", 30, channel="legacy")  # a row from a retired channel
    add("n5", "other", 5)
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    yield s
    app.dependency_overrides.clear()
    s.close()


@pytest.fixture
def client(db):
    return TestClient(app)


FAM = {"X-Person-Id": "fam"}


def test_list_only_own_web_rows_newest_first(client):
    r = client.get("/me/notifications", headers=FAM)
    assert r.status_code == 200
    body = r.json()
    assert [n["id"] for n in body["notifications"]] == ["n3", "n2", "n1"]
    assert body["unread_count"] == 2
    assert body["notifications"][0]["patient_display_name"] == "Rosa (ficticia)"
    assert all(n["channel"] == "web" for n in body["notifications"])


def test_since_filters_list_but_not_unread_count(client):
    since = (NOW + timedelta(minutes=5)).isoformat()
    r = client.get("/me/notifications", params={"since": since}, headers=FAM)
    body = r.json()
    assert [n["id"] for n in body["notifications"]] == ["n3", "n2"]
    assert body["unread_count"] == 2


def test_unread_only_and_limit(client):
    body = client.get("/me/notifications?unread_only=true", headers=FAM).json()
    assert [n["id"] for n in body["notifications"]] == ["n2", "n1"]
    body = client.get("/me/notifications?limit=1", headers=FAM).json()
    assert [n["id"] for n in body["notifications"]] == ["n3"]


def test_mark_read_is_idempotent(client, db):
    first = client.post("/me/notifications/n1/read", headers=FAM)
    assert first.status_code == 200 and first.json()["read_at"] is not None
    stamp = first.json()["read_at"]
    second = client.post("/me/notifications/n1/read", headers=FAM)
    assert second.json()["read_at"] == stamp
    assert client.get("/me/notifications", headers=FAM).json()["unread_count"] == 1


def test_cannot_read_someone_elses_or_legacy_row(client):
    assert client.post("/me/notifications/n5/read", headers=FAM).status_code == 404
    assert client.post("/me/notifications/n4/read", headers=FAM).status_code == 404
    r = client.post("/me/notifications/nope/read", headers=FAM)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    # n5 untouched
    other = client.get("/me/notifications", headers={"X-Person-Id": "other"}).json()
    assert other["unread_count"] == 1


def test_read_all(client):
    r = client.post("/me/notifications/read-all", headers=FAM)
    assert r.json() == {"updated": 2}
    assert client.get("/me/notifications", headers=FAM).json()["unread_count"] == 0
    assert client.post("/me/notifications/read-all", headers=FAM).json() == {"updated": 0}
    assert client.get("/me/notifications", headers={"X-Person-Id": "other"}).json()["unread_count"] == 1


def test_read_all_for_one_patient(client, db):
    db.add(Patient(id="pat_y", display_name="Otra (ficticia)"))
    db.add(Notification(id="n6", patient_id="pat_y", person_id="fam", recipient="family",
                        channel=NotificationChannel.web.value, status=NotificationStatus.sent,
                        title="t", body="b", created_at=NOW))
    db.commit()
    assert client.post("/me/notifications/read-all?patient_id=pat_x", headers=FAM).json() == {"updated": 2}
    page = client.get("/me/notifications", headers=FAM).json()
    assert page["unread_count"] == 1 and [n["id"] for n in page["notifications"] if not n["read_at"]] == ["n6"]


def test_read_all_urgent_false_keeps_emergency_alerts(client):
    assert client.post("/me/notifications/read-all?patient_id=pat_x&urgent=false", headers=FAM).json() == {"updated": 0}
    assert client.get("/me/notifications", headers=FAM).json()["unread_count"] == 2


def test_emergency_rows_are_urgent(client):
    assert all(n["urgent"] for n in client.get("/me/notifications", headers=FAM).json()["notifications"])


def test_requires_auth(client):
    assert client.get("/me/notifications").status_code == 401
    assert client.post("/me/notifications/n1/read").status_code == 401
    assert client.post("/me/notifications/read-all").status_code == 401
