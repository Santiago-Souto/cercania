"""POST /patients, GET /patients/{id}/members, POST /patients/{id}/invites. Fictional data only."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import patients as patients_api
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


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = Session(engine)
    for pid, phone in [("cg", "+15550100001"), ("fam", "+15550100002"), ("doc", "+15550100003"),
                       ("new", "+15550100009")]:
        s.add(Person(id=pid, phone=phone, display_name=f"{pid} (ficticio)"))
    s.get(Person, "new").is_caregiver = True  # caregiver an admin registered before assigning patients (CIA-48)
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


def test_reinvite_returns_the_pending_invite_instead_of_duplicating(db):
    first = client.post("/patients/pat_a/invites", json={"contact": "+59899111111", "role": "family"},
                        headers=h("cg")).json()
    r = client.post("/patients/pat_a/invites", json={"contact": "+59899111111"}, headers=h("cg"))
    assert r.status_code == 200
    assert r.json() == first
    assert len(db.scalars(select(Invite)).all()) == 1


@pytest.mark.parametrize("role", ["caregiver", "doctor", "nurse", "institution"])
def test_invites_are_family_or_patient_only(db, role):
    r = client.post("/patients/pat_a/invites", json={"contact": "+59899111111", "role": role}, headers=h("cg"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "invite_role"
    assert db.scalars(select(Invite)).all() == []


def test_patient_invite_gives_the_patient_their_own_login(db):
    inv = client.post("/patients/pat_a/invites", json={"contact": "+15550100009", "role": "patient"}, headers=h("cg")).json()
    assert inv["role"] == "patient"
    r = client.post(f"/me/invites/{inv['id']}/accept", headers=h("new"))
    assert r.json() == {"patient_id": "pat_a", "display_name": "Rosa (ficticia)", "role": "patient"}
    # One own login per patient.
    r = client.post("/patients/pat_a/invites", json={"contact": "+59899111111", "role": "patient"}, headers=h("cg"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "patient_has_login"


def test_new_patient_invite_creates_their_profile_with_the_inviter_as_caregiver(db):
    r = client.post("/invites", json={"contact": "+15550100009", "role": "patient"}, headers=h("cg"))
    assert r.status_code == 201
    [mine] = client.get("/me/invites", headers=h("new")).json()["invites"]
    assert mine["patient_id"] is None and mine["role"] == "patient"
    r = client.post(f"/me/invites/{mine['id']}/accept", headers=h("new"))
    assert r.status_code == 200 and r.json()["role"] == "patient"
    new_patient = r.json()["patient_id"]
    roles_there = {a.person_id: a.role for a in db.scalars(select(PatientAccess).where(PatientAccess.patient_id == new_patient))}
    assert roles_there == {"new": Role.patient, "cg": Role.caregiver}


@pytest.mark.parametrize("person, body, status, code", [
    ("cg", {"role": "family"}, 422, "patient_required"),
    ("fam", {"role": "patient"}, 403, "forbidden"),  # not a caregiver
    ("fam", {"role": "family", "patient_id": "pat_a"}, 403, "forbidden"),  # family cannot invite
    ("cg", {"role": "doctor", "patient_id": "pat_a"}, 422, "invite_role"),
])
def test_caregiver_invite_rules(db, person, body, status, code):
    r = client.post("/invites", json={"contact": "+59899111111", **body}, headers=h(person))
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_family_invite_through_the_general_endpoint(db):
    r = client.post("/invites", json={"contact": "+59899111111", "role": "family", "patient_id": "pat_a"}, headers=h("cg"))
    assert r.status_code == 201 and r.json()["role"] == "family"


@pytest.mark.parametrize("contact", ["ana@example.com", "099111111", "+0123"])
def test_invite_rejects_email_and_bad_numbers(db, contact):
    r = client.post("/patients/pat_a/invites", json={"contact": contact, "role": "family"}, headers=h("cg"))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "phone_invalid"


def test_invite_existing_member_conflicts(db):
    r = client.post("/patients/pat_a/invites", json={"contact": "+15550100002", "role": "family"},
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


def invite_new(role="family"):
    """cg invites the registered non-member `new` (+15550100009)."""
    r = client.post("/patients/pat_a/invites", json={"contact": "+15550100009", "role": role}, headers=h("cg"))
    assert r.status_code == 201
    return r.json()["id"]


def test_invited_person_sees_the_invite_and_nothing_is_joined_yet(db):
    inv = invite_new()
    r = client.get("/me/invites", headers=h("new"))
    assert r.status_code == 200
    [mine] = r.json()["invites"]
    assert {k: mine[k] for k in ("id", "patient_id", "patient_display_name", "role", "invited_by")} == {
        "id": inv, "patient_id": "pat_a", "patient_display_name": "Rosa (ficticia)",
        "role": "family", "invited_by": "cg (ficticio)"}
    assert client.get("/me", headers=h("new")).json()["memberships"] == []
    assert client.get("/patients/pat_a/reports", headers=h("new")).status_code == 404
    assert client.get("/me/invites", headers=h("fam")).json() == {"invites": []}


def test_accepting_creates_the_membership(db):
    inv = invite_new()
    r = client.post(f"/me/invites/{inv}/accept", headers=h("new"))
    assert r.status_code == 200
    assert r.json() == {"patient_id": "pat_a", "display_name": "Rosa (ficticia)", "role": "family"}
    assert db.get(Invite, inv).status == InviteStatus.accepted
    assert client.get("/patients/pat_a/reports", headers=h("new")).status_code == 200
    assert client.get("/me/invites", headers=h("new")).json() == {"invites": []}
    m = client.get("/patients/pat_a/members", headers=h("cg")).json()
    assert ("new", "family") in [(x["user_id"], x["role"]) for x in m["members"]]
    assert m["invites"] == []
    # No longer pending: a second accept is a 404.
    assert client.post(f"/me/invites/{inv}/accept", headers=h("new")).status_code == 404


def test_declining_deletes_the_invite_and_allows_a_new_one(db):
    inv = invite_new()
    r = client.post(f"/me/invites/{inv}/decline", headers=h("new"))
    assert r.status_code == 200 and r.json() == {"status": "declined"}
    assert db.get(Invite, inv) is None
    assert client.get("/patients/pat_a/members", headers=h("cg")).json()["invites"] == []
    assert client.get("/me", headers=h("new")).json()["memberships"] == []
    invite_new()  # the caregiver can invite the number again


def test_nobody_else_can_answer_someone_elses_invite(db):
    inv = invite_new()
    for pid in ("cg", "fam"):
        for action in ("accept", "decline"):
            r = client.post(f"/me/invites/{inv}/{action}", headers=h(pid))
            assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert db.get(Invite, inv).status == InviteStatus.pending


def test_my_invites_need_a_session(db, monkeypatch):
    monkeypatch.delenv("ALLOW_DEV_IDENTITY_HEADER")
    assert client.get("/me/invites").status_code == 401
    assert client.post("/me/invites/inv_x/accept").status_code == 401


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
    r = client.post("/patients/pat_a/invites", json={"contact": "+59899111111", "role": "family"}, headers=h("cg"))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == winner.id and r.json()["role"] == "family"
    assert len(db.scalars(select(Invite)).all()) == 1


# --- Emergency contact (CIA-51) ---

def test_emergency_contact_permission_matrix():
    from app.models import ROLE_PERMISSIONS, Permission
    allowed = {r for r, perms in ROLE_PERMISSIONS.items() if Permission.edit_emergency_contact in perms}
    assert allowed == {Role.caregiver, Role.doctor}


def test_create_patient_with_and_without_emergency_contact(db):
    r = client.post("/patients", json={"display_name": "Ana (ficticia)"}, headers=h("cg"))
    assert r.json()["emergency_contact"] is None
    body = {"display_name": "Ana (ficticia)",
            "emergency_contact": {"name": " Emergencias Residencia ", "phone": "+598 99 111 222"}}
    r = client.post("/patients", json=body, headers=h("cg"))
    assert r.status_code == 201, r.text
    assert r.json()["emergency_contact"] == {"name": "Emergencias Residencia", "phone": "+59899111222"}
    assert client.get(f"/patients/{r.json()['id']}", headers=h("cg")).json()["emergency_contact"]["phone"] == "+59899111222"


def test_create_patient_rejects_bad_emergency_phone(db):
    body = {"display_name": "Ana", "emergency_contact": {"name": "X", "phone": "099111111"}}
    r = client.post("/patients", json=body, headers=h("cg"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "phone_invalid"
    assert db.scalar(select(Patient).where(Patient.id != "pat_a")) is None


@pytest.mark.parametrize("person", ["cg", "doc"])
def test_caregiver_and_doctor_set_and_clear_emergency_contact(db, person):
    r = client.patch("/patients/pat_a/emergency-contact",
                     json={"name": "Residencia (ficticia)", "phone": "+15550100077"}, headers=h(person))
    assert r.status_code == 200, r.text
    assert r.json()["emergency_contact"] == {"name": "Residencia (ficticia)", "phone": "+15550100077"}
    assert client.get("/patients/pat_a", headers=h("fam")).json()["emergency_contact"]["name"] == "Residencia (ficticia)"
    r = client.patch("/patients/pat_a/emergency-contact", content="null",
                     headers=h(person) | {"Content-Type": "application/json"})
    assert r.status_code == 200
    assert r.json()["emergency_contact"] is None


def test_other_roles_cannot_edit_emergency_contact(db):
    db.add(Person(id="nur", phone="+15550100004", display_name="nur"))
    db.add(PatientAccess(person_id="nur", patient_id="pat_a", role=Role.nurse))
    db.commit()
    for person in ("fam", "nur"):
        r = client.patch("/patients/pat_a/emergency-contact",
                         json={"name": "X", "phone": "+15550100077"}, headers=h(person))
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "forbidden"
    assert client.get("/patients/pat_a", headers=h("cg")).json()["emergency_contact"] is None


def test_patch_emergency_contact_invalid_phone_is_422(db):
    r = client.patch("/patients/pat_a/emergency-contact", json={"name": "X", "phone": "abc"}, headers=h("cg"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "phone_invalid"


def _self_signed_up_patient(db, person_id="new"):
    """Like sign-up with no invite: the person gets their own profile, then asks for help."""
    from app import roles
    from app.models import PatientMessage, PatientMessageKind
    person = db.get(Person, person_id)
    person.is_caregiver = False
    own = roles.own_patient_profile(db, person)
    db.add(PatientMessage(patient_id=own.id, sender_id=person_id, kind=PatientMessageKind.help))
    db.commit()
    return own.id


def test_self_signed_up_patient_accepting_an_invite_merges_their_own_profile(db):
    from app.models import PatientMessage
    own = _self_signed_up_patient(db)
    inv = client.post("/patients/pat_a/invites", json={"contact": "+15550100009", "role": "patient"}, headers=h("cg")).json()
    # The invite reaches them even though they already have a profile.
    assert [i["id"] for i in client.get("/me/invites", headers=h("new")).json()["invites"]] == [inv["id"]]
    r = client.post(f"/me/invites/{inv['id']}/accept", headers=h("new"))
    assert r.status_code == 200 and r.json()["patient_id"] == "pat_a"
    # One profile left; the help request moved with them and the caregiver now sees it.
    assert [(m["patient_id"], m["role"]) for m in client.get("/me", headers=h("new")).json()["memberships"]] == [("pat_a", "patient")]
    assert db.get(Patient, own).archived_at is not None
    assert [m.patient_id for m in db.scalars(select(PatientMessage))] == ["pat_a"]
    assert len(client.get("/patients/pat_a/patient-messages", headers=h("cg")).json()["messages"]) == 1


def test_own_profile_with_a_team_is_not_merged(db):
    own = _self_signed_up_patient(db)
    db.add(PatientAccess(person_id="doc", patient_id=own, role=Role.doctor))
    db.commit()
    inv = client.post("/patients/pat_a/invites", json={"contact": "+15550100009", "role": "patient"}, headers=h("cg")).json()
    client.post(f"/me/invites/{inv['id']}/accept", headers=h("new"))
    assert db.get(Patient, own).archived_at is None
    assert len(client.get("/me", headers=h("new")).json()["memberships"]) == 2


def test_caregiver_archives_a_patient(db):
    from app.models import RoleChange
    client.post("/patients/pat_a/invites", json={"contact": "+59899111111", "role": "family"}, headers=h("cg"))
    r = client.delete("/patients/pat_a", headers=h("cg"))
    assert r.status_code == 200 and r.json() == {"status": "archived"}
    assert db.get(Patient, "pat_a").archived_at is not None
    for pid in ("cg", "fam", "doc"):
        assert client.get("/me/patients", headers=h(pid)).json() == {"patients": []}
        assert client.get("/patients/pat_a", headers=h(pid)).status_code == 404
    assert db.scalars(select(Invite).where(Invite.patient_id == "pat_a")).all() == []
    log = db.scalar(select(RoleChange).where(RoleChange.action == "patient_archived"))
    assert {m["person_id"] for m in log.before["memberships"]} == {"cg", "fam", "doc"}


@pytest.mark.parametrize("person", ["fam", "doc"])
def test_only_caregivers_archive(db, person):
    r = client.delete("/patients/pat_a", headers=h(person))
    assert r.status_code == 403
    assert db.get(Patient, "pat_a").archived_at is None
