"""Read routes: patients, reports, alerts, /me. Fictional data only."""

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
    CarePlan,
    ChecklistItem,
    Medication,
    Patient,
    PatientAccess,
    Person,
    Report,
    ReportItem,
    ReportVersion,
    Role,
    TriageStatus,
    VersionSource,
)

NOW = datetime.now(timezone.utc)
client = TestClient(app)


def h(person_id):
    return {"X-Person-Id": person_id}


@pytest.fixture(autouse=True)
def dev_identity(monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADER", "1")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = Session(engine)
    s.add(Patient(id="pat_a", display_name="Rosa (ficticia)"))
    s.add(Patient(id="pat_b", display_name="Ana (ficticia)"))
    s.add(CarePlan(id="plan_a", patient_id="pat_a", version=1, indications=["hidratación"], allergies=["penicilina"]))
    s.add(Medication(id="med_a", care_plan_id="plan_a", name="Enalapril", dose_text="1 comprimido", times=["08:00"]))
    for pid, phone in [("cg", "+15550100001"), ("fam", "+15550100002"), ("doc", "+15550100003"),
                       ("pt", "+15550100004"), ("out", "+15550100005")]:
        s.add(Person(id=pid, phone=phone, display_name=pid))
    for pid, role in [("cg", Role.caregiver), ("fam", Role.family), ("doc", Role.doctor), ("pt", Role.patient)]:
        s.add(PatientAccess(person_id=pid, patient_id="pat_a", role=role))
    s.add(PatientAccess(person_id="cg", patient_id="pat_b", role=Role.caregiver))

    # rep_1: emergency, 1 h ago
    s.add(Report(id="rep_1", patient_id="pat_a", sender_id="cg", transcript="se cayó en el baño",
                 created_at=NOW - timedelta(hours=1), red_flag=True, triage_status=TriageStatus.ok,
                 triage_reason="caída", triage_quote="se cayó en el baño", triage_quote_verified=True))
    s.add(ReportVersion(id="rv_1", report_id="rep_1", version=1, source=VersionSource.original, created_by="cg"))
    s.add(ReportItem(report_version_id="rv_1", item=ChecklistItem.incidents, value="caída", quote="se cayó en el baño"))
    s.add(Alert(id=1, report_version_id="rv_1", type=AlertType.emergency, detail="caída",
                evidence_quote="se cayó en el baño", evidence_verified=True, created_at=NOW - timedelta(hours=1)))
    s.add(Alert(id=2, report_version_id="rv_1", type=AlertType.missing_item, item=ChecklistItem.sleep,
                detail="sueño no mencionado", created_at=NOW - timedelta(hours=1)))

    # rep_2: corrected, 3 h ago; only v2 alerts count
    s.add(Report(id="rep_2", patient_id="pat_a", sender_id="cg", transcript="comió poco",
                 created_at=NOW - timedelta(hours=3)))
    s.add(ReportVersion(id="rv_2a", report_id="rep_2", version=1, source=VersionSource.original, created_by="cg"))
    s.add(ReportVersion(id="rv_2b", report_id="rep_2", version=2, source=VersionSource.correction, created_by="fam"))
    s.add(ReportItem(report_version_id="rv_2a", item=ChecklistItem.appetite, value="poco"))
    s.add(ReportItem(report_version_id="rv_2b", item=ChecklistItem.appetite, value="bien"))
    s.add(Alert(id=3, report_version_id="rv_2a", type=AlertType.change, item=ChecklistItem.appetite,
                detail="v1 alert", created_at=NOW - timedelta(hours=3)))
    s.add(Alert(id=4, report_version_id="rv_2b", type=AlertType.omission, item=ChecklistItem.medication,
                detail="v2 alert", plan_ref="med_a", created_at=NOW - timedelta(hours=2, minutes=50)))

    # rep_3: old, 48 h ago
    s.add(Report(id="rep_3", patient_id="pat_a", sender_id="cg", transcript="día tranquilo",
                 created_at=NOW - timedelta(hours=48)))
    s.add(ReportVersion(id="rv_3", report_id="rep_3", version=1, source=VersionSource.original, created_by="cg"))
    s.add(Alert(id=5, report_version_id="rv_3", type=AlertType.change, detail="old alert",
                created_at=NOW - timedelta(hours=48)))
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    yield s
    app.dependency_overrides.clear()
    s.close()


def test_get_patient(db):
    r = client.get("/patients/pat_a", headers=h("pt"))  # patient role may read the care plan
    assert r.status_code == 200
    body = r.json()
    assert body["display_name"] == "Rosa (ficticia)"
    assert body["care_plan"]["allergies"] == ["penicilina"]
    assert body["care_plan"]["medications"][0]["dose"] == "1 comprimido"


def test_reports_list_shape_and_order(db):
    r = client.get("/patients/pat_a/reports", headers=h("fam"))
    assert r.status_code == 200
    body = r.json()
    assert [x["id"] for x in body["reports"]] == ["rep_1", "rep_2", "rep_3"]
    assert body["next_before"] is None
    first = body["reports"][0]
    assert first["red_flag"] is True and first["triage"]["quote_verified"] is True
    assert first["alerts"][0]["report_id"] == "rep_1"
    assert body["reports"][1]["version"] == 2


def test_reports_pagination(db):
    r1 = client.get("/patients/pat_a/reports?limit=2", headers=h("cg")).json()
    assert [x["id"] for x in r1["reports"]] == ["rep_1", "rep_2"]
    assert r1["next_before"] is not None
    r2 = client.get("/patients/pat_a/reports", params={"limit": 2, "before": r1["next_before"]}, headers=h("cg")).json()
    assert [x["id"] for x in r2["reports"]] == ["rep_3"]
    assert r2["next_before"] is None
    assert client.get("/patients/pat_a/reports?limit=0", headers=h("cg")).status_code == 422
    assert client.get("/patients/pat_a/reports?limit=101", headers=h("cg")).status_code == 422


def test_alerts_latest_version_only_and_since(db):
    r = client.get("/patients/pat_a/alerts", headers=h("doc"))
    assert r.status_code == 200
    alerts = r.json()["alerts"]
    ids = [a["id"] for a in alerts]
    assert ids == [2, 1, 4, 5]  # newest first, ties by id desc
    assert 3 not in ids  # superseded by the correction
    by_id = {a["id"]: a for a in alerts}
    assert by_id[4]["report_id"] == "rep_2" and by_id[4]["report_version"] == 2
    assert by_id[1]["type"] == "emergency"
    created = [a["created_at"] for a in alerts]
    assert created == sorted(created, reverse=True)
    since = (NOW - timedelta(hours=5)).isoformat()
    r = client.get("/patients/pat_a/alerts", params={"since": since}, headers=h("doc"))
    assert {a["id"] for a in r.json()["alerts"]} == {1, 2, 4}
    r = client.get("/patients/pat_a/alerts", params={"since": (NOW - timedelta(minutes=30)).isoformat()},
                   headers=h("doc"))
    assert r.json()["alerts"] == []
    r = client.get("/patients/pat_a/alerts?limit=1", headers=h("doc"))
    assert len(r.json()["alerts"]) == 1


def test_report_and_versions(db):
    r = client.get("/reports/rep_2", headers=h("fam"))
    assert r.status_code == 200 and r.json()["version"] == 2
    assert [i["value"] for i in r.json()["items"]] == ["bien"]
    v = client.get("/reports/rep_2/versions", headers=h("fam")).json()
    assert v["report_id"] == "rep_2"
    assert [x["version"] for x in v["versions"]] == [1, 2]
    assert v["versions"][1]["source"] == "correction" and v["versions"][1]["created_by"]["id"] == "fam"
    assert v["versions"][0]["alerts"][0]["id"] == 3


def test_access_rules(db):
    for url in ("/patients/pat_a/reports", "/patients/pat_a/alerts", "/reports/rep_1", "/reports/rep_1/versions"):
        denied = client.get(url, headers=h("pt"))
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "forbidden"
        assert client.get(url, headers=h("out")).status_code == 404
        assert client.get(url).status_code == 401
    assert client.get("/patients/pat_a", headers=h("out")).status_code == 404
    assert client.get("/reports/nope", headers=h("cg")).status_code == 404
    # caregiver of another patient cannot read pat_a's report via pat_b access
    assert client.get("/patients/pat_b/reports", headers=h("fam")).status_code == 404


def test_me(db):
    r = client.get("/me", headers=h("cg"))
    assert r.status_code == 200
    body = r.json()
    assert body["phone_last4"] == "0001" and body["display_name"] == "cg"
    assert [(m["display_name"], m["role"]) for m in body["memberships"]] == [
        ("Ana (ficticia)", "caregiver"), ("Rosa (ficticia)", "caregiver")]
    r = client.get("/me", headers=h("ghost"))
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_my_patients(db):
    body = client.get("/me/patients", headers=h("cg")).json()
    by_id = {p["id"]: p for p in body["patients"]}
    assert [p["id"] for p in body["patients"]] == ["pat_b", "pat_a"]
    a = by_id["pat_a"]
    assert a["role"] == "caregiver" and a["red_flag"] is True and a["missing_report"] is False
    assert a["open_alerts"] == 2  # emergency (rep_1) + v2 omission (rep_2); missing_item and old/v1 excluded
    assert a["last_report_at"] is not None
    b = by_id["pat_b"]
    assert b["last_report_at"] is None and b["red_flag"] is False
    assert b["missing_report"] is True and b["open_alerts"] == 0


def test_my_patients_nulls_for_patient_role(db):
    body = client.get("/me/patients", headers=h("pt")).json()
    assert body["patients"] == [{"id": "pat_a", "display_name": "Rosa (ficticia)", "location": None,
                                 "role": "patient", "last_report_at": None, "open_alerts": None,
                                 "red_flag": None, "missing_report": None}]
    assert client.get("/me/patients").status_code == 401
