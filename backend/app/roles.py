"""Who gets which role, and how (CIA-48, CIA-58). Code only; the model never decides access.

- A person has one role (`person.role`). Admins set only that, never links to patients (CIA-58).
- Self sign-up: a new person with no admin pre-registration and no pending invite gets their
  own patient profile and the `patient` role on it.
- Admin pre-registration (phone + role): applied when that phone signs up.
- Caregivers invite family or patients; only caregivers create patients. Nobody links the
  health team to patients yet (README "Pending").
- Admins list people and set roles. Being admin opens no clinical data.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Invite,
    InviteStatus,
    Notification,
    Patient,
    PatientAccess,
    PatientMessage,
    Person,
    PreRegistration,
    Report,
    Role,
    RoleChange,
    utcnow,
)

ADMIN = "admin"
# What an older account (no `person.role` yet) reads as: its strongest membership role.
_DERIVED_ORDER = [Role.caregiver, Role.doctor, Role.nurse, Role.institution, Role.family, Role.patient]


def is_admin(person: Person | None) -> bool:
    return bool(person and person.is_admin)


def person_role(session: Session, person: Person) -> str | None:
    """The person's role: `person.role` once set (CIA-58). Older accounts: the legacy
    `is_caregiver` flag, else their strongest membership role, else None."""
    if person.role:
        return person.role
    if person.is_caregiver:
        return Role.caregiver.value
    held = set(session.scalars(select(PatientAccess.role).where(PatientAccess.person_id == person.id)))
    return next((r.value for r in _DERIVED_ORDER if r in held), None)


def is_caregiver(session: Session, person: Person) -> bool:
    """Only caregivers create patients and invite without a patient (CIA-48)."""
    return person_role(session, person) == Role.caregiver.value


def person_state(session: Session, person: Person) -> dict:
    """What an admin sees about a person, and what a 409 shows before an overwrite: who they
    are and their role. No links to patients (CIA-58)."""
    return {
        "id": person.id,
        "name": person.display_name,
        "phone": person.phone,
        "is_admin": bool(person.is_admin),
        "role": person_role(session, person),
    }


def pre_registration_state(session: Session, pre: PreRegistration) -> dict:
    return {"id": pre.id, "phone": pre.phone, "role": pre.role, "created_at": pre.created_at}


def log(session: Session, action: str, *, actor_id: str | None, person_id: str | None = None,
        phone: str | None = None, patient_id: str | None = None,
        before: dict | None = None, after: dict | None = None) -> None:
    session.add(RoleChange(actor_id=actor_id, action=action, person_id=person_id, phone=phone,
                           patient_id=patient_id, before=before, after=after))


PATIENT_HAS_LOGIN = "Este paciente ya tiene su propio acceso."
PROFILE_EXISTS = "Esa persona ya tiene su perfil de paciente. Pedí a una persona administradora que te sume a su equipo."


def has_own_profile(session: Session, person: Person | None) -> bool:
    """The person already holds the `patient` role on some profile (their own)."""
    return person is not None and session.scalar(
        select(PatientAccess.id).where(PatientAccess.person_id == person.id,
                                       PatientAccess.role == Role.patient).limit(1)
    ) is not None


def other_patient_login(session: Session, patient_id: str, person_id: str | None) -> bool:
    """Someone other than `person_id` is already this patient's own login (one per patient)."""
    stmt = select(PatientAccess.id).where(PatientAccess.patient_id == patient_id, PatientAccess.role == Role.patient)
    if person_id is not None:
        stmt = stmt.where(PatientAccess.person_id != person_id)
    return session.scalar(stmt.limit(1)) is not None


def own_patient_profile(session: Session, person: Person) -> Patient:
    """The person's own patient profile (role `patient`), created if they have none."""
    existing = session.scalar(
        select(Patient).join(PatientAccess, PatientAccess.patient_id == Patient.id)
        .where(PatientAccess.person_id == person.id, PatientAccess.role == Role.patient)
    )
    if existing is not None:
        return existing
    patient = Patient(display_name=person.display_name)
    session.add(patient)
    session.flush()
    session.add(PatientAccess(person_id=person.id, patient_id=patient.id, role=Role.patient))
    return patient


def set_membership(session: Session, person: Person, patient_id: str, role: Role) -> PatientAccess:
    access = session.scalar(select(PatientAccess).where(PatientAccess.person_id == person.id,
                                                        PatientAccess.patient_id == patient_id))
    if access is None:
        access = PatientAccess(person_id=person.id, patient_id=patient_id, role=role)
        session.add(access)
    else:
        access.role = role
    return access


def archive_patient(session: Session, patient: Patient, actor_id: str | None) -> None:
    """Soft delete: drop every membership, pending invite and pre-registration for the patient,
    so nobody reaches it any more. Reports, versions and messages stay (evidence trail); the
    memberships it had are kept in the `role_change` log."""
    accesses = session.scalars(select(PatientAccess).where(PatientAccess.patient_id == patient.id)).all()
    log(session, "patient_archived", actor_id=actor_id, patient_id=patient.id,
        before={"memberships": [{"person_id": a.person_id, "role": a.role.value} for a in accesses]})
    for a in accesses:
        session.delete(a)
    for model in (Invite, PreRegistration):
        for row in session.scalars(select(model).where(model.patient_id == patient.id)):
            if model is PreRegistration or row.status == InviteStatus.pending:
                session.delete(row)
    patient.archived_at = utcnow()
    session.flush()


def merge_own_profile(session: Session, person: Person, into_patient_id: str) -> bool:
    """A self-signed-up patient accepted a caregiver's invite as the login of another profile.
    If their own profile is only theirs (no one else with access, no reports), its patient
    messages move to the new profile and the old one is archived: one person, one profile.
    Returns whether it merged."""
    old = session.scalar(
        select(Patient).join(PatientAccess, PatientAccess.patient_id == Patient.id)
        .where(PatientAccess.person_id == person.id, PatientAccess.role == Role.patient,
               Patient.id != into_patient_id)
    )
    if old is None:
        return False
    others = session.scalar(select(PatientAccess.id).where(PatientAccess.patient_id == old.id,
                                                           PatientAccess.person_id != person.id).limit(1))
    reports = session.scalar(select(Report.id).where(Report.patient_id == old.id).limit(1))
    if others is not None or reports is not None:
        return False
    for model in (PatientMessage, Notification):
        for row in session.scalars(select(model).where(model.patient_id == old.id)):
            row.patient_id = into_patient_id
    log(session, "own_profile_merged", actor_id=person.id, person_id=person.id, patient_id=into_patient_id,
        before={"patient_id": old.id}, after={"patient_id": into_patient_id})
    archive_patient(session, old, person.id)
    return True


def set_person_role(session: Session, person: Person, role: str) -> list[str]:
    """Set the person's role (CIA-58). Never links them to someone else's patient.

    - `patient`: their own profile, created if they have none.
    - Any other role: their `patient` logins are removed, so nobody stays their own patient while
      holding another role. The profiles and their records stay.

    Returns the ids of the patients whose login was removed (for the log).
    """
    person.role = role
    if role == Role.patient.value:
        own_patient_profile(session, person)
        session.flush()
        return []
    logins = session.scalars(select(PatientAccess).where(PatientAccess.person_id == person.id,
                                                         PatientAccess.role == Role.patient)).all()
    for access in logins:
        session.delete(access)
    session.flush()
    return [a.patient_id for a in logins]


def apply_role(session: Session, person: Person, role: str) -> None:
    """Give an existing person a role from a pre-registration (or an admin's confirmed change).

    Callers validate and confirm first (an admin role on an existing person needs confirmation).
    `admin` is a flag on top of the person's role, which stays.
    """
    if role == ADMIN:
        person.is_admin = True
        session.flush()
    else:
        set_person_role(session, person, role)


def claim_patient_by_phone(session: Session, person: Person) -> Patient | None:
    """A caregiver added a patient with this person's phone: they become its own login, no invite.

    Only a live patient with no login yet; the phone was proven by the SMS code.
    """
    patient = session.scalar(
        select(Patient).where(Patient.phone == person.phone, Patient.archived_at.is_(None))
        .order_by(Patient.created_at, Patient.id)
    )
    if patient is None or other_patient_login(session, patient.id, person.id):
        return None
    set_membership(session, person, patient.id, Role.patient)
    session.flush()
    log(session, "patient_phone_claimed", actor_id=None, person_id=person.id, phone=person.phone,
        patient_id=patient.id, after={"role": Role.patient.value, "patient_id": patient.id})
    return patient


def on_signup(session: Session, person: Person) -> str:
    """Decide a brand-new person's starting role. Returns what was applied (for logs and tests).

    Pre-registration first (it is the admin's explicit decision); then a patient a caregiver
    added with this phone (they join it as its own login); a pending invite stays to be
    accepted in the app; otherwise the person signed up for themselves: patient.
    """
    pre = session.scalar(select(PreRegistration).where(PreRegistration.phone == person.phone))
    if pre is not None:
        # Role only: a legacy `patient_id` on the pre-registration is ignored (CIA-58).
        apply_role(session, person, pre.role)
        log(session, "pre_registration_applied", actor_id=pre.created_by, person_id=person.id,
            phone=person.phone, after={"role": pre.role})
        session.delete(pre)
        return f"pre_registration:{pre.role}"
    if claim_patient_by_phone(session, person) is not None:
        person.role = Role.patient.value
        return "patient_phone"
    invited = session.scalar(select(Invite.id).where(Invite.phone == person.phone,
                                                     Invite.status == InviteStatus.pending).limit(1))
    if invited is not None:
        return "invite_pending"
    set_person_role(session, person, Role.patient.value)
    return "self_signup_patient"


def _has_membership(session: Session, person: Person) -> bool:
    return session.scalar(select(PatientAccess.id).where(PatientAccess.person_id == person.id).limit(1)) is not None


def ensure_default_role(session: Session, person: Person) -> bool:
    """A person left with no role at all is a patient (CIA-48 default): give them their own profile.

    Covers accounts from before the sign-up rule or a declined invite. Admins, anyone with a role
    (`person.role`, or the legacy caregiver flag) and anyone with a pending invite are left as they
    are: a doctor an admin set has no patients yet and is not made one. Returns True when a profile
    was created.
    """
    if person.is_admin or person.role or person.is_caregiver or _has_membership(session, person):
        return False
    # Lock the person row, then check again: two concurrent requests (login, a double-mounted
    # My patients) must not each create a profile. Postgres waits here; SQLite has one writer.
    session.execute(select(Person.id).where(Person.id == person.id).with_for_update())
    if _has_membership(session, person):
        return False
    if claim_patient_by_phone(session, person) is not None:
        person.role = Role.patient.value
        return False
    if session.scalar(select(Invite.id).where(Invite.phone == person.phone,
                                              Invite.status == InviteStatus.pending).limit(1)) is not None:
        return False
    person.role = Role.patient.value
    patient = own_patient_profile(session, person)
    session.flush()
    log(session, "default_patient_applied", actor_id=None, person_id=person.id, phone=person.phone,
        patient_id=patient.id, after={"role": Role.patient.value, "patient_id": patient.id})
    return True
