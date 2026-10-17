from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Patient, PatientAccess, Permission, Person, Role, can


def make_session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    s.add(Patient(id="pat_x", display_name="Test (ficticio)"))
    for pid, role in [("cg", Role.caregiver), ("fam", Role.family),
                      ("doc", Role.doctor), ("pt", Role.patient)]:
        s.add(Person(id=pid, phone=f"+1555010{len(pid)}{pid}", display_name=pid))
        s.add(PatientAccess(person_id=pid, patient_id="pat_x", role=role))
    s.add(Person(id="stranger", phone="+15550109999", display_name="stranger"))
    s.commit()
    return s


def test_only_doctor_edits_care_plan():
    s = make_session()
    assert can(s, "doc", "pat_x", Permission.edit_care_plan)
    for pid in ("cg", "fam", "pt"):
        assert not can(s, pid, "pat_x", Permission.edit_care_plan)


def test_patient_cannot_read_reports_but_sees_plan():
    s = make_session()
    assert not can(s, "pt", "pat_x", Permission.read_reports)
    assert can(s, "pt", "pat_x", Permission.read_care_plan)


def test_only_caregiver_sends_reports():
    s = make_session()
    assert can(s, "cg", "pat_x", Permission.send_report)
    for pid in ("fam", "doc", "pt"):
        assert not can(s, pid, "pat_x", Permission.send_report)


def test_no_access_without_link():
    s = make_session()
    assert not can(s, "stranger", "pat_x", Permission.read_care_plan)
