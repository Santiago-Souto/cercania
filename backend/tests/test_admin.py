"""Admins, pre-registration, person roles and the sign-up rule (CIA-48, CIA-58). Fictional data only; no SMS is sent."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import patient_messages, sms
from app.deps import get_db
from app.main import app
from app.models import (
    Base,
    Invite,
    Patient,
    PatientAccess,
    Person,
    PreRegistration,
    Role,
    RoleChange,
)

CG, FAM, ADM = "+15550100001", "+15550100002", "+15550100041"
NEW = "+15550100009"
client = TestClient(app, base_url="https://testserver")


def h(person_id):
    return {"X-Person-Id": person_id}


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADER", "1")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = Session(engine)
    s.add(Patient(id="pat_a", display_name="Rosa (ficticia)"))
    s.add(Patient(id="pat_b", display_name="Jorge (ficticio)"))
    s.add(Person(id="cg", phone=CG, display_name="Ana (ficticia)"))
    s.add(Person(id="fam", phone=FAM, display_name="Carmen (ficticia)"))
    s.add(Person(id="adm", phone=ADM, display_name="Admin (ficticio)", is_admin=True))
    s.add(PatientAccess(person_id="cg", patient_id="pat_a", role=Role.caregiver))
    s.add(PatientAccess(person_id="fam", patient_id="pat_a", role=Role.family))
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    yield s
    app.dependency_overrides.clear()
    s.close()


@pytest.fixture
def signup(monkeypatch):
    """Signs a new phone up through the real /auth endpoints (SMS captured), returns its session client."""
    sent = []
    monkeypatch.setattr(sms, "send_sms", lambda to, body, client=None: sent.append(body) or sms.SmsResult(True))
    monkeypatch.delenv("AUTH_DEV_LOG_CODES", raising=False)
    monkeypatch.delenv("TWILIO_TRIAL_TEMPLATE", raising=False)

    def do(phone=NEW, name="Nueva (ficticia)"):
        c = TestClient(app, base_url="https://testserver")
        assert c.post("/auth/signup", json={"name": name, "phone": phone}).status_code == 200
        code = next(w for w in sent[-1].replace(".", " ").split() if w.isdigit() and len(w) == 6)
        r = c.post("/auth/verify", json={"phone": phone, "code": code})
        assert r.status_code == 200, r.text
        return c, r.json()

    return do


def person(db, phone):
    return db.scalar(select(Person).where(Person.phone == phone))


# --- sign-up rule ----------------------------------------------------------------------------


def test_self_signup_becomes_patient_of_their_own_profile(db, signup):
    c, verified = signup()
    [m] = verified["memberships"]
    assert m["role"] == "patient" and m["display_name"] == "Nueva (ficticia)"
    assert verified["is_admin"] is False
    me = c.get("/me").json()
    assert me["can_add_patients"] is False and me["is_admin"] is False
    assert c.post("/patients", json={"display_name": "Otra (ficticia)"}).status_code == 403


def test_signup_with_pending_invite_gets_no_profile_and_accepts_as_family(db, signup):
    client.post("/patients/pat_a/invites", json={"contact": NEW}, headers=h("cg"))
    c, verified = signup()
    assert verified["memberships"] == []
    [inv] = c.get("/me/invites").json()["invites"]
    assert c.post(f"/me/invites/{inv['id']}/accept").json()["role"] == "family"


def test_person_with_no_role_becomes_patient_on_my_patients(db):
    db.add(Person(id="old", phone=NEW, display_name="Vieja (ficticia)"))
    db.commit()
    [p] = client.get("/me/patients", headers=h("old")).json()["patients"]
    assert p["role"] == "patient" and p["display_name"] == "Vieja (ficticia)"
    assert client.get("/me/patients", headers=h("old")).json()["patients"] == [p]  # only once
    assert db.scalar(select(RoleChange).where(RoleChange.action == "default_patient_applied")).person_id == "old"


def test_person_with_no_role_becomes_patient_on_login(db, signup):
    db.add(Person(id="old", phone=NEW, display_name="Vieja (ficticia)"))
    db.commit()
    _, verified = signup()  # existing phone: the code logs in
    assert [m["role"] for m in verified["memberships"]] == ["patient"]


def test_no_default_patient_for_admin_caregiver_role_or_pending_invite(db):
    db.add(Person(id="cg2", phone="+15550100031", display_name="Cuidadora (ficticia)", is_caregiver=True))
    db.add(Person(id="doc", phone="+15550100032", display_name="Médica (ficticia)", role="doctor"))
    db.add(Person(id="inv", phone=NEW, display_name="Invitada (ficticia)"))
    db.commit()
    client.post("/patients/pat_a/invites", json={"contact": NEW}, headers=h("cg"))
    for pid in ("adm", "cg2", "doc", "inv"):
        assert client.get("/me/patients", headers=h(pid)).json()["patients"] == []


@pytest.mark.parametrize("role", ["caregiver", "doctor", "family"])
def test_pre_registered_phone_starts_with_that_role_and_no_patients(db, signup, role):
    r = client.post("/admin/pre-registrations", json={"phone": NEW, "role": role}, headers=h("adm"))
    assert r.status_code == 201, r.text
    _, verified = signup()
    assert verified["memberships"] == []  # an admin never links people to patients (CIA-58)
    assert person(db, NEW).role == role
    assert db.scalars(select(PreRegistration)).all() == []  # consumed
    assert db.scalar(select(RoleChange).where(RoleChange.action == "pre_registration_applied")).actor_id == "adm"


def test_pre_registered_caregiver_without_patient_is_not_made_a_patient(db, signup):
    client.post("/admin/pre-registrations", json={"phone": NEW, "role": "caregiver"}, headers=h("adm"))
    c, verified = signup()
    assert verified["memberships"] == []
    me = c.get("/me").json()
    assert me["can_add_patients"] is True and me["memberships"] == []
    r = c.post("/patients", json={"display_name": "Elena (ficticia)"})
    assert r.status_code == 201  # their first patient; they become its caregiver
    assert [(m["role"]) for m in c.get("/me").json()["memberships"]] == ["caregiver"]


def test_pre_registered_admin_and_patient(db, signup):
    client.post("/admin/pre-registrations", json={"phone": NEW, "role": "admin"}, headers=h("adm"))
    _, verified = signup()
    assert verified["is_admin"] is True and verified["memberships"] == []
    client.post("/admin/pre-registrations", json={"phone": "+15550100010", "role": "patient"}, headers=h("adm"))
    _, verified = signup(phone="+15550100010", name="Paciente (ficticio)")
    assert [m["role"] for m in verified["memberships"]] == ["patient"]


def test_pre_registration_wins_over_a_pending_invite(db, signup):
    client.post("/patients/pat_a/invites", json={"contact": NEW}, headers=h("cg"))
    client.post("/admin/pre-registrations", json={"phone": NEW, "role": "nurse"}, headers=h("adm"))
    c, verified = signup()
    assert verified["memberships"] == [] and person(db, NEW).role == "nurse"
    assert len(c.get("/me/invites").json()["invites"]) == 1  # still there to accept


# --- pre-registration validation and overwrite warning -----------------------------------------


def test_pre_registration_takes_no_patient(db):
    """CIA-58: a pre-registration is phone + role. A patient sent by an old client is ignored."""
    r = client.post("/admin/pre-registrations", json={"phone": NEW, "role": "family", "patient_id": "pat_a"}, headers=h("adm"))
    assert r.status_code == 201
    assert r.json()["pre_registration"].keys() == {"id", "phone", "role", "created_at"}
    assert db.scalar(select(PreRegistration)).patient_id is None


def test_existing_phone_needs_confirmation_including_to_become_admin(db):
    r = client.post("/admin/pre-registrations", json={"phone": FAM, "role": "caregiver"}, headers=h("adm"))
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "overwrite_required"
    assert err["current"]["person"] == {"id": "fam", "name": "Carmen (ficticia)", "phone": FAM, "is_admin": False, "role": "family"}
    assert person(db, FAM).role is None

    r = client.post("/admin/pre-registrations", json={"phone": FAM, "role": "caregiver", "confirm_overwrite": True},
                    headers=h("adm"))
    assert r.status_code == 200 and r.json()["applied_to"]["role"] == "caregiver"
    # Her link to Rosa is not the admin's to change: it stays.
    assert db.scalar(select(PatientAccess).where(PatientAccess.person_id == "fam")).role == Role.family

    # Another admin can make an existing person admin, after the same confirmation.
    r = client.post("/admin/pre-registrations", json={"phone": FAM, "role": "admin"}, headers=h("adm"))
    assert r.status_code == 409
    assert not person(db, FAM).is_admin
    r = client.post("/admin/pre-registrations", json={"phone": FAM, "role": "admin", "confirm_overwrite": True}, headers=h("adm"))
    assert r.status_code == 200 and r.json()["applied_to"]["is_admin"] is True
    assert r.json()["applied_to"]["role"] == "caregiver"  # their role stays


def test_pending_pre_registration_needs_confirmation_to_replace(db):
    client.post("/admin/pre-registrations", json={"phone": NEW, "role": "caregiver"}, headers=h("adm"))
    r = client.post("/admin/pre-registrations", json={"phone": NEW, "role": "nurse"}, headers=h("adm"))
    assert r.status_code == 409 and r.json()["error"]["current"]["pre_registration"]["role"] == "caregiver"
    r = client.post("/admin/pre-registrations", json={"phone": NEW, "role": "nurse", "confirm_overwrite": True},
                    headers=h("adm"))
    assert r.status_code == 200 and r.json()["pre_registration"]["role"] == "nurse"
    assert len(db.scalars(select(PreRegistration)).all()) == 1


def test_edit_and_delete_pre_registration(db):
    pre = client.post("/admin/pre-registrations", json={"phone": NEW, "role": "caregiver"}, headers=h("adm")).json()["pre_registration"]
    r = client.patch(f"/admin/pre-registrations/{pre['id']}", json={"role": "family"}, headers=h("adm"))
    assert r.json()["pre_registration"]["role"] == "family"
    assert client.delete(f"/admin/pre-registrations/{pre['id']}", headers=h("adm")).status_code == 200
    assert db.scalars(select(PreRegistration)).all() == []


# --- person roles (CIA-58) ---------------------------------------------------------------------


def test_admin_lists_people_with_their_role_and_no_patients(db):
    client.post("/admin/pre-registrations", json={"phone": NEW, "role": "caregiver"}, headers=h("adm"))
    body = client.get("/admin/people", headers=h("adm")).json()
    assert body.keys() == {"people", "pre_registrations"}
    assert {p["name"]: p["role"] for p in body["people"]} == {
        "Ana (ficticia)": "caregiver", "Carmen (ficticia)": "family", "Admin (ficticio)": None}
    assert all("memberships" not in p for p in body["people"])
    assert [(p["phone"], p["role"]) for p in body["pre_registrations"]] == [(NEW, "caregiver")]


def test_changing_a_role_needs_confirmation_and_is_logged(db):
    r = client.put("/admin/people/fam/role", json={"role": "doctor"}, headers=h("adm"))
    assert r.status_code == 409 and r.json()["error"]["current"]["role"] == "family"
    assert person(db, FAM).role is None
    r = client.put("/admin/people/fam/role", json={"role": "doctor", "confirm_overwrite": True}, headers=h("adm"))
    assert r.status_code == 200 and r.json()["role"] == "doctor"
    assert db.scalar(select(PatientAccess).where(PatientAccess.person_id == "fam")).role == Role.family  # link untouched
    assert client.put("/admin/people/fam/role", json={"role": "doctor"}, headers=h("adm")).status_code == 200  # same: no-op
    log = [(c.action, c.before, c.after) for c in db.scalars(select(RoleChange).order_by(RoleChange.id))]
    assert log == [("role_set", {"role": "family"}, {"role": "doctor"})]


def test_a_person_with_no_role_gets_one_without_confirmation(db):
    db.add(Person(id="nr", phone=NEW, display_name="Sin rol (ficticia)"))
    db.commit()
    r = client.put("/admin/people/nr/role", json={"role": "nurse"}, headers=h("adm"))
    assert r.status_code == 200 and r.json()["role"] == "nurse"
    assert client.get("/me/patients", headers=h("nr")).json()["patients"] == []  # not made a patient


def test_self_signed_up_patient_made_caregiver_loses_their_own_login(db, signup):
    """The Felipe case: signed up alone (own profile), then an admin makes them a caregiver."""
    c, verified = signup()
    own = verified["memberships"][0]["patient_id"]
    pid = person(db, NEW).id
    r = client.put(f"/admin/people/{pid}/role", json={"role": "caregiver"}, headers=h("adm"))
    assert r.status_code == 409 and r.json()["error"]["current"]["role"] == "patient"
    r = client.put(f"/admin/people/{pid}/role", json={"role": "caregiver", "confirm_overwrite": True}, headers=h("adm"))
    assert r.status_code == 200 and r.json()["role"] == "caregiver"
    assert c.get("/me/patients").json()["patients"] == []  # no longer their own patient, and no new profile
    assert c.get("/me").json()["can_add_patients"] is True
    assert db.get(Patient, own) is not None  # the profile and its records stay
    assert db.scalar(select(RoleChange).where(RoleChange.action == "role_set")).after == {
        "role": "caregiver", "patient_logins_removed": [own]}


def test_becoming_a_patient_creates_their_own_profile_and_keeps_other_links(db):
    r = client.put("/admin/people/cg/role", json={"role": "patient", "confirm_overwrite": True}, headers=h("adm"))
    assert r.status_code == 200 and r.json()["role"] == "patient"
    held = {(a.patient_id, a.role) for a in db.scalars(select(PatientAccess).where(PatientAccess.person_id == "cg"))}
    assert ("pat_a", Role.caregiver) in held and len(held) == 2
    own = next(pid for pid, role in held if role == Role.patient)
    assert db.get(Patient, own).display_name == "Ana (ficticia)"


def test_admin_cannot_link_people_to_patients(db):
    for call in (client.put, client.delete):
        kwargs = {"json": {"role": "doctor"}} if call is client.put else {}
        assert call("/admin/people/fam/memberships/pat_b", headers=h("adm"), **kwargs).status_code in (404, 405)
    assert db.scalar(select(PatientAccess).where(PatientAccess.patient_id == "pat_b")) is None


def test_unknown_role_or_person(db):
    assert client.put("/admin/people/fam/role", json={"role": "admin"}, headers=h("adm")).status_code == 422
    assert client.put("/admin/people/nobody/role", json={"role": "family"}, headers=h("adm")).status_code == 404


# --- access ----------------------------------------------------------------------------------


@pytest.mark.parametrize("call", [
    lambda: client.get("/admin/people", headers=h("cg")),
    lambda: client.put("/admin/people/fam/role", json={"role": "doctor"}, headers=h("cg")),
    lambda: client.post("/admin/pre-registrations", json={"phone": NEW, "role": "admin"}, headers=h("fam")),
    lambda: client.put("/admin/people/fam/admin", json={"confirm_overwrite": True}, headers=h("fam")),
])
def test_non_admins_get_403(db, call):
    r = call()
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


def test_admin_sees_no_clinical_data(db):
    assert client.get("/patients/pat_a", headers=h("adm")).status_code == 404
    assert client.get("/patients/pat_a/reports", headers=h("adm")).status_code == 404
    assert client.get("/patients/pat_a/alerts", headers=h("adm")).status_code == 404
    assert client.post("/patients", json={"display_name": "X (ficticio)"}, headers=h("adm")).status_code == 403
    assert client.get("/me", headers=h("adm")).json()["is_admin"] is True


def test_only_caregivers_create_patients(db):
    assert client.post("/patients", json={"display_name": "X (ficticio)"}, headers=h("cg")).status_code == 201
    assert client.post("/patients", json={"display_name": "X (ficticio)"}, headers=h("fam")).status_code == 403


# --- safety: a patient alone ------------------------------------------------------------------


def test_help_with_an_empty_team_says_nobody_was_notified(db, signup):
    c, verified = signup()
    patient_id = verified["memberships"][0]["patient_id"]
    r = c.post(f"/patients/{patient_id}/patient-messages", json={"kind": "help"})
    assert r.status_code == 200
    assert r.json()["notified"] == []
    assert r.json()["message_for_patient"] == patient_messages.NO_TEAM_MESSAGE
    assert "emergencias" in r.json()["message_for_patient"]



def test_signup_with_a_new_patient_invite_waits_for_the_accept(db, signup):
    client.post("/invites", json={"contact": NEW, "role": "patient"}, headers=h("cg"))
    c, verified = signup()
    assert verified["memberships"] == []  # no automatic profile: the invite creates it
    [inv] = c.get("/me/invites").json()["invites"]
    r = c.post(f"/me/invites/{inv['id']}/accept")
    assert r.json()["role"] == "patient"
    members = {m["user_id"]: m["role"] for m in client.get(f"/patients/{r.json()['patient_id']}/members", headers=h("cg")).json()["members"]}
    assert members[person(db, NEW).id] == "patient" and members["cg"] == "caregiver"


def test_admin_makes_an_existing_person_admin_after_confirming(db):
    r = client.put("/admin/people/cg/admin", json={}, headers=h("adm"))
    assert r.status_code == 409
    current = r.json()["error"]["current"]
    assert current["name"] == "Ana (ficticia)" and current["role"] == "caregiver"
    assert not person(db, CG).is_admin
    r = client.put("/admin/people/cg/admin", json={"confirm_overwrite": True}, headers=h("adm"))
    assert r.status_code == 200 and r.json()["is_admin"] is True and r.json()["role"] == "caregiver"
    assert client.get("/admin/people", headers=h("cg")).status_code == 200  # Ana can now admin
    assert db.scalar(select(RoleChange).where(RoleChange.action == "admin_granted")).actor_id == "adm"
    assert client.put("/admin/people/fam/admin", json={"confirm_overwrite": True}, headers=h("fam")).status_code == 403



def test_new_patient_invite_never_opens_an_existing_profile(db, signup):
    """Tenki #55: someone who already has their own profile cannot be invited into it as a 'new' patient."""
    _, verified = signup()  # self sign-up: own profile
    own = verified["memberships"][0]["patient_id"]
    r = client.post("/invites", json={"contact": NEW, "role": "patient"}, headers=h("cg"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "profile_exists"
    # Even an invite that slipped in earlier cannot be accepted into the existing profile.
    db.add(Invite(patient_id=None, phone=NEW, role=Role.patient, invited_by="cg"))
    db.commit()
    [inv] = client.get("/me/invites", headers=h(person(db, NEW).id)).json()["invites"]
    r = client.post(f"/me/invites/{inv['id']}/accept", headers=h(person(db, NEW).id))
    assert r.status_code == 409 and r.json()["error"]["code"] == "profile_exists"
    assert db.scalar(select(PatientAccess).where(PatientAccess.patient_id == own, PatientAccess.person_id == "cg")) is None
