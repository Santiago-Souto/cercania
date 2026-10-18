"""POST /patients, GET /patients/{id}/members, POST /patients/{id}/invites. Fictional data only."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import patients as patients_api
from app.api.auth import _accept_invites
from app.deps import get_db
from app.main import app
from app.models import (
    Base,
    CarePlan,
    Invite,
    InviteStatus,
    Medication,
    Patient,
    PatientAccess,
    Person,
    Role,
)

client = TestClient(app)


def h(person_id):
    return {"X-Person-Id": person_id}


@pytest.fixture(autouse=True)
def dev_identity(monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADER", "1")
    monkeypatch.delenv("NOTIFY_WHATSAPP", raising=False)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = Session(engine)
    for pid, phone in [("cg", "+15550100001"), ("fam", "+15550100002"), ("doc", "+15550100003"),
                       ("new", "+15550100009")]:
        s.add(Person(id=pid, phone=phone, display_name=f"{pid} (ficticio)"))
    s.add(Patient(id="pat_a", display_name="Rosa (ficticia)"))
    for pid, role in [("cg", Role.caregiver), ("fam", Role.family), ("doc", Role.doctor)]:
        s.add(PatientAccess(person_id=pid, patient_id="pat_a", role=role))
    s.commit()

    def override():
        yield s

    app.dependency_overrides[get_db] = override
    yield s
    app.dependency_overrides.clear()
    s.close()


BODY = {
    "display_name": "  Elena (ficticia) ",
    "location": "Hab. 7",
    "care_plan": {
        "medications": [{"name": "Medicamento A", "dose": "1 comprimido", "times": ["08:00", "20:00"]}],
        "indications": ["Hidratación frecuente"],
        "allergies": ["Penicilina"],
    },
}


def test_create_patient_stores_plan_and_makes_creator_caregiver(db):
    r = client.post("/patients", json=BODY, headers=h("new"))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["display_name"] == "Elena (ficticia)"
    assert data["location"] == "Hab. 7"
    assert data["care_plan"]["medications"][0] | {"id": None} == {
        "id": None, "name": "Medicamento A", "dose": "1 comprimido", "times": ["08:00", "20:00"]}
    assert data["care_plan"]["indications"] == ["Hidratación frecuente"]
    assert data["care_plan"]["allergies"] == ["Penicilina"]

    access = db.scalar(select(PatientAccess).where(PatientAccess.patient_id == data["id"]))
    assert (access.person_id, access.role) == ("new", Role.caregiver)
    plan = db.scalar(select(CarePlan).where(CarePlan.patient_id == data["id"]))
    assert (plan.version, plan.created_by) == (1, "new")
    assert db.scalar(select(Medication).where(Medication.care_plan_id == plan.id)).dose_text == "1 comprimido"

    mine = client.get("/me/patients", headers=h("new")).json()["patients"]
    assert [(p["id"], p["role"]) for p in mine] == [(data["id"], "caregiver")]


def test_create_patient_minimal_body(db):
    r = client.post("/patients", json={"display_name": "Tomás (ficticio)"}, headers=h("cg"))
    assert r.status_code == 201
    assert r.json()["location"] is None
    assert r.json()["care_plan"] == {"medications": [], "indications": [], "allergies": []}


@pytest.mark.parametrize("body", [
    {"display_name": "   "},
    {"display_name": "X", "care_plan": {"medications": [{"name": "A", "dose": "1", "times": ["25:00"]}]}},
    {"display_name": "X", "care_plan": {"medications": [{"name": "A", "dose": " ", "times": []}]}},
])
def test_create_patient_validation(db, body):
    r = client.post("/patients", json=body, headers=h("cg"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"
    assert db.scalar(select(Patient).where(Patient.id != "pat_a")) is None


def test_create_patient_requires_identity(db):
    assert client.post("/patients", json=BODY).status_code == 401
    assert client.post("/patients", json=BODY, headers=h("ghost")).status_code == 401


def test_invite_then_members_lists_it_as_pending(db):
    r = client.post("/patients/pat_a/invites", json={"contact": "+598 99 111 111", "role": "family"},
                    headers=h("cg"))
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["contact"] == "+59899111111" and inv["role"] == "family" and inv["status"] == "pending"

    m = client.get("/patients/pat_a/members", headers=h("cg")).json()
    assert [(x["user_id"], x["role"]) for x in m["members"]] == [
        ("cg", "caregiver"), ("fam", "family"), ("doc", "doctor")]
    assert m["invites"] == [inv]


def test_reinvite_updates_role_instead_of_duplicating(db):
    first = client.post("/patients/pat_a/invites", json={"contact": "+59899111111", "role": "family"},
                        headers=h("cg")).json()
    r = client.post("/patients/pat_a/invites", json={"contact": "+59899111111", "role": "nurse"},
                    headers=h("cg"))
    assert r.status_code == 200
    assert r.json() == {**first, "role": "nurse"}
    assert len(db.scalars(select(Invite)).all()) == 1


@pytest.mark.parametrize("contact", ["ana@example.com", "099111111", "+0123"])
def test_invite_rejects_email_and_bad_numbers(db, contact):
    r = client.post("/patients/pat_a/invites", json={"contact": contact, "role": "family"}, headers=h("cg"))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "phone_invalid"


def test_invite_existing_member_conflicts(db):
    r = client.post("/patients/pat_a/invites", json={"contact": "+15550100002", "role": "doctor"},
                    headers=h("cg"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "already_member"


@pytest.mark.parametrize("person", ["fam", "doc"])
def test_only_caregivers_invite(db, person):
    r = client.post("/patients/pat_a/invites", json={"contact": "+59899111111", "role": "family"},
                    headers=h(person))
    assert r.status_code == 403


def test_members_hide_invited_numbers_from_non_caregivers(db):
    client.post("/patients/pat_a/invites", json={"contact": "+59899111111", "role": "family"}, headers=h("cg"))
    m = client.get("/patients/pat_a/members", headers=h("fam")).json()
    assert len(m["members"]) == 3 and m["invites"] == []


def test_members_access(db):
    assert client.get("/patients/pat_a/members", headers=h("new")).status_code == 404
    db.add(PatientAccess(person_id="new", patient_id="pat_a", role=Role.patient))
    db.commit()
    assert client.get("/patients/pat_a/members", headers=h("new")).status_code == 403


def test_invite_becomes_membership_on_login(db):
    client.post("/patients/pat_a/invites", json={"contact": "+15550100009", "role": "nurse"}, headers=h("cg"))
    _accept_invites(db, db.get(Person, "new"))
    db.commit()
    m = client.get("/patients/pat_a/members", headers=h("cg")).json()
    assert ("new", "nurse") in [(x["user_id"], x["role"]) for x in m["members"]]
    assert m["invites"] == []
    assert db.scalar(select(Invite)).status == InviteStatus.accepted


def test_invite_whatsapp_only_when_enabled(db, monkeypatch):
    sent = []
    monkeypatch.setattr(patients_api.whatsapp, "send_text_result",
                        lambda to, text: sent.append((to, text)) or patients_api.whatsapp.SendResult(True))
    client.post("/patients/pat_a/invites", json={"contact": "+59899111111", "role": "family"}, headers=h("cg"))
    assert sent == []
    monkeypatch.setenv("NOTIFY_WHATSAPP", "1")
    client.post("/patients/pat_a/invites", json={"contact": "+59899222222", "role": "family"}, headers=h("cg"))
    assert sent[0][0] == "59899222222"
    assert "Rosa (ficticia)" in sent[0][1] and "familia" in sent[0][1]


def test_db_allows_one_pending_invite_per_patient_and_phone(db):
    from sqlalchemy.exc import IntegrityError

    db.add(Invite(patient_id="pat_a", phone="+59899111111", role=Role.family))
    db.commit()
    db.add(Invite(patient_id="pat_a", phone="+59899111111", role=Role.nurse))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    # Accepted invites do not count: the same phone can be invited again later.
    db.scalar(select(Invite)).status = InviteStatus.accepted
    db.add(Invite(patient_id="pat_a", phone="+59899111111", role=Role.nurse))
    db.commit()


def test_invite_insert_race_updates_the_winner(db, monkeypatch):
    """The pending lookup misses (another request is mid-insert), the insert hits the unique index,
    and the endpoint updates the row that won instead of failing."""
    winner = Invite(patient_id="pat_a", phone="+59899111111", role=Role.family)
    db.add(winner)
    db.commit()
    real = patients_api._pending_invite
    calls = []

    def first_misses(*args):
        calls.append(1)
        return None if len(calls) == 1 else real(*args)

    monkeypatch.setattr(patients_api, "_pending_invite", first_misses)
    r = client.post("/patients/pat_a/invites", json={"contact": "+59899111111", "role": "nurse"}, headers=h("cg"))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == winner.id and r.json()["role"] == "nurse"
    assert len(db.scalars(select(Invite)).all()) == 1
