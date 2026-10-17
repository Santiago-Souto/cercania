"""Foundation: serializers match schemas, access dependency rules, error handlers, CORS."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import schemas, serializers
from app.deps import PatientContext, get_db, patient_access, report_access
from app.errors import install_error_handlers
from app.main import app as main_app
from app.models import (
    Alert,
    AlertType,
    Base,
    CarePlan,
    ChecklistItem,
    Medication,
    Patient,
    PatientAccess,
    Permission,
    Person,
    Report,
    ReportItem,
    ReportKind,
    ReportVersion,
    Role,
    TriageStatus,
    VersionSource,
)


@pytest.fixture(autouse=True)
def dev_identity(monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADER", "1")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Patient(id="pat_x", display_name="Rosa (ficticia)"))
    session.add(CarePlan(id="plan_x", patient_id="pat_x", version=1, indications=["hidratación"], allergies=[]))
    session.add(Medication(id="med_x", care_plan_id="plan_x", name="Enalapril", dose_text="1 comprimido", times=["08:00"]))
    for pid, role in [("cg", Role.caregiver), ("fam", Role.family), ("pt", Role.patient)]:
        session.add(Person(id=pid, phone=f"+1555020{pid}", display_name=pid))
        session.add(PatientAccess(person_id=pid, patient_id="pat_x", role=role))
    session.add(Person(id="out", phone="+15550209999", display_name="out"))
    session.add(Report(id="rep_1", patient_id="pat_x", sender_id="cg", transcript="se cayó en el baño",
                       red_flag=True, triage_status=TriageStatus.ok, triage_reason="caída",
                       triage_quote="se cayó en el baño", triage_quote_verified=True))
    session.add(ReportVersion(id="rv_1", report_id="rep_1", version=1, source=VersionSource.original,
                              created_by="cg", confirmation_text="Registrado."))
    session.add(ReportItem(report_version_id="rv_1", item=ChecklistItem.incidents, value="caída",
                           level="alert", quote="se cayó en el baño", quote_verified=True))
    session.add(ReportItem(report_version_id="rv_1", item=ChecklistItem.sleep))
    session.add(Alert(report_version_id="rv_1", type=AlertType.emergency, detail="caída",
                      evidence_quote="se cayó en el baño", evidence_verified=True,
                      notifications=[{"to": "family", "person_id": "fam", "channel": "web", "status": "sent", "error": None}]))
    session.commit()
    yield session
    session.close()


def test_serialize_report_matches_schema(db):
    out = serializers.serialize_report(db, db.get(Report, "rep_1"))
    assert set(out) == set(schemas.Report.model_fields)
    assert out["caregiver"] == out["sender"] and out["sender"]["role"] == "caregiver"
    assert out["red_flag_quote"] == "se cayó en el baño"
    assert out["triage"]["emergency"] is True
    assert out["missing_items"] == ["sleep"]
    assert out["alerts"][0]["type"] == "emergency" and out["alerts"][0]["report_id"] == "rep_1"
    assert out["audio_url"] is None
    model = schemas.Report.model_validate(out)
    assert {i.item for i in model.items} == {"incidents", "sleep"}


def test_emergency_kind_has_no_missing_items_and_seed_has_no_triage(db):
    report = db.get(Report, "rep_1")
    report.kind = ReportKind.emergency
    assert serializers.serialize_report(db, report)["missing_items"] == []
    report.triage_status = None
    assert serializers.serialize_report(db, report)["triage"] is None


def test_serialize_version_and_process_result(db):
    version = serializers.serialize_version(db, db.get(ReportVersion, "rv_1"))
    schemas.ReportVersion.model_validate(version)
    assert version["created_by"]["id"] == "cg"
    result = serializers.process_result(db, db.get(Report, "rep_1"))
    assert result["status"] == "ok" and result["report"] == {"id": "rep_1", "version": 1}
    assert result["red_flag"] is True and result["confirmation_text"] == "Registrado."


def test_serialize_patient(db):
    out = serializers.serialize_patient(db, db.get(Patient, "pat_x"))
    schemas.Patient.model_validate(out)
    assert out["care_plan"]["medications"] == [
        {"id": "med_x", "name": "Enalapril", "dose": "1 comprimido", "times": ["08:00"]}]


def test_access_dependency_rules(db):
    app = FastAPI()
    install_error_handlers(app)
    app.dependency_overrides[get_db] = lambda: db

    @app.get("/patients/{patient_id}/x")
    def route(ctx: PatientContext = Depends(patient_access(Permission.read_reports))):
        return {"role": ctx.role.value}

    c = TestClient(app)
    ok = c.get("/patients/pat_x/x", headers={"X-Person-Id": "fam"})
    assert ok.status_code == 200 and ok.json() == {"role": "family"}
    assert c.get("/patients/pat_x/x", headers={"X-Person-Id": "out"}).status_code == 404
    assert c.get("/patients/nope/x", headers={"X-Person-Id": "fam"}).status_code == 404
    denied = c.get("/patients/pat_x/x", headers={"X-Person-Id": "pt"})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "forbidden"


def test_report_access(db):
    report, role = report_access(db, "fam", "rep_1", Permission.read_reports)
    assert report.id == "rep_1" and role == Role.family
    for person, status in [("out", 404), ("pt", 403)]:
        with pytest.raises(Exception) as exc:
            report_access(db, person, "rep_1", Permission.read_reports)
        assert exc.value.status_code == status
    with pytest.raises(Exception) as exc:
        report_access(db, "fam", "rep_nope", Permission.read_reports)
    assert exc.value.status_code == 404


def test_validation_error_shape():
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/q")
    def q(body: schemas.QueryRequest):
        return {}

    r = TestClient(app).post("/q", json={"question": ""})
    assert r.status_code == 422
    assert r.json() == {"error": {"code": "invalid_request", "message": "Revisá los datos enviados."}}


def test_cors_preflight_allows_web_origin():
    r = TestClient(main_app).options(
        "/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET",
                 "Access-Control-Request-Headers": "X-Person-Id"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert r.headers["access-control-allow-credentials"] == "true"


def test_naive_datetimes_leave_as_utc():
    """SQLite returns naive datetimes; the web must get an explicit offset."""
    from datetime import datetime

    from app.schemas import MyPatient

    out = MyPatient(id="pat_x", display_name="x", role="family",
                    last_report_at=datetime(2026, 10, 17, 22, 0)).model_dump(mode="json")
    assert out["last_report_at"] == "2026-10-17T22:00:00Z"
