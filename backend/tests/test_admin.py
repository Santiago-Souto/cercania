"""Admins, pre-registration and the sign-up rule (CIA-48). Fictional data only; no SMS is sent."""

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


@pytest.mark.parametrize("role, patient, expected", [
    ("caregiver", "pat_a", [("pat_a", "caregiver")]),
    ("doctor", "pat_b", [("pat_b", "doctor")]),
])
def test_pre_registered_phone_starts_with_that_membership(db, signup, role, patient, expected):
    r = client.post("/admin/pre-registrations", json={"phone": NEW, "role": role, "patient_id": patient}, headers=h("adm"))
    assert r.status_code == 201, r.text
    _, verified = signup()
    assert [(m["patient_id"], m["role"]) for m in verified["memberships"]] == expected
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
    client.post("/admin/pre-registrations", json={"phone": NEW, "role": "nurse", "patient_id": "pat_b"}, headers=h("adm"))
    c, verified = signup()
    assert [(m["patient_id"], m["role"]) for m in verified["memberships"]] == [("pat_b", "nurse")]
    assert len(c.get("/me/invites").json()["invites"]) == 1  # still there to accept


# --- pre-registration validation and overwrite warning -----------------------------------------


@pytest.mark.parametrize("body, code", [
    ({"role": "family"}, "patient_required"),
    ({"role": "doctor"}, "patient_required"),
    ({"role": "admin", "patient_id": "pat_a"}, "patient_not_used"),
    ({"role": "patient", "patient_id": "pat_a"}, "patient_not_used"),
])
def test_pre_registration_patient_rules(db, body, code):
    r = client.post("/admin/pre-registrations", json={"phone": NEW, **body}, headers=h("adm"))
    assert r.status_code == 422 and r.json()["error"]["code"] == code


def test_existing_phone_needs_confirmation_and_never_becomes_admin(db):
    r = client.post("/admin/pre-registrations", json={"phone": FAM, "role": "caregiver", "patient_id": "pat_b"},
                    headers=h("adm"))
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "overwrite_required"
    assert err["current"]["person"]["name"] == "Carmen (ficticia)"
    assert err["current"]["person"]["memberships"] == [{"patient_id": "pat_a", "patient_name": "Rosa (ficticia)", "role": "family"}]
    assert db.scalar(select(PatientAccess).where(PatientAccess.person_id == "fam", PatientAccess.patient_id == "pat_b")) is None

    r = client.post("/admin/pre-registrations", json={"phone": FAM, "role": "caregiver", "patient_id": "pat_b",
                                                      "confirm_overwrite": True}, headers=h("adm"))
    assert r.status_code == 200
    assert ("pat_b", "caregiver") in [(m["patient_id"], m["role"]) for m in r.json()["applied_to"]["memberships"]]

    for confirm in (False, True):
        r = client.post("/admin/pre-registrations", json={"phone": FAM, "role": "admin", "confirm_overwrite": confirm},
                        headers=h("adm"))
        assert r.status_code == 422 and r.json()["error"]["code"] == "cannot_promote"
    assert not person(db, FAM).is_admin


def test_pending_pre_registration_needs_confirmation_to_replace(db):
    client.post("/admin/pre-registrations", json={"phone": NEW, "role": "caregiver"}, headers=h("adm"))
    r = client.post("/admin/pre-registrations", json={"phone": NEW, "role": "nurse", "patient_id": "pat_a"}, headers=h("adm"))
    assert r.status_code == 409 and r.json()["error"]["current"]["pre_registration"]["role"] == "caregiver"
    r = client.post("/admin/pre-registrations", json={"phone": NEW, "role": "nurse", "patient_id": "pat_a",
                                                      "confirm_overwrite": True}, headers=h("adm"))
    assert r.status_code == 200 and r.json()["pre_registration"]["role"] == "nurse"
    assert len(db.scalars(select(PreRegistration)).all()) == 1


def test_edit_and_delete_pre_registration(db):
    pre = client.post("/admin/pre-registrations", json={"phone": NEW, "role": "caregiver"}, headers=h("adm")).json()["pre_registration"]
    r = client.patch(f"/admin/pre-registrations/{pre['id']}", json={"role": "family", "patient_id": "pat_a"}, headers=h("adm"))
    assert r.json()["pre_registration"]["patient_name"] == "Rosa (ficticia)"
    assert client.delete(f"/admin/pre-registrations/{pre['id']}", headers=h("adm")).status_code == 200
    assert db.scalars(select(PreRegistration)).all() == []


# --- memberships -----------------------------------------------------------------------------


def test_admin_lists_people_pre_registrations_and_patient_names(db):
    client.post("/admin/pre-registrations", json={"phone": NEW, "role": "caregiver"}, headers=h("adm"))
    body = client.get("/admin/people", headers=h("adm")).json()
    assert {p["name"] for p in body["people"]} == {"Ana (ficticia)", "Carmen (ficticia)", "Admin (ficticio)"}
    assert [(p["phone"], p["role"]) for p in body["pre_registrations"]] == [(NEW, "caregiver")]
    assert body["patients"] == [{"id": "pat_b", "display_name": "Jorge (ficticio)"},
                                {"id": "pat_a", "display_name": "Rosa (ficticia)"}]


def test_replacing_a_role_on_a_patient_needs_confirmation_and_is_logged(db):
    r = client.put("/admin/people/fam/memberships/pat_a", json={"role": "caregiver"}, headers=h("adm"))
    assert r.status_code == 409 and r.json()["error"]["current"]["memberships"][0]["role"] == "family"
    r = client.put("/admin/people/fam/memberships/pat_a", json={"role": "caregiver", "confirm_overwrite": True}, headers=h("adm"))
    assert r.status_code == 200 and r.json()["memberships"][0]["role"] == "caregiver"
    # A new patient for the same person is not an overwrite.
    r = client.put("/admin/people/fam/memberships/pat_b", json={"role": "doctor"}, headers=h("adm"))
    assert r.status_code == 200
    r = client.delete("/admin/people/fam/memberships/pat_b", headers=h("adm"))
    assert [m["patient_id"] for m in r.json()["memberships"]] == ["pat_a"]
    log = [(c.action, c.before, c.after) for c in db.scalars(select(RoleChange).order_by(RoleChange.id))]
    assert log == [("membership_set", {"role": "family"}, {"role": "caregiver"}),
                   ("membership_set", None, {"role": "doctor"}),
                   ("membership_removed", {"role": "doctor"}, None)]


# --- access ----------------------------------------------------------------------------------


@pytest.mark.parametrize("call", [
    lambda: client.get("/admin/people", headers=h("cg")),
    lambda: client.put("/admin/people/fam/memberships/pat_b", json={"role": "doctor"}, headers=h("cg")),
    lambda: client.post("/admin/pre-registrations", json={"phone": NEW, "role": "admin"}, headers=h("fam")),
    lambda: client.delete("/admin/people/fam/memberships/pat_a", headers=h("fam")),
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
