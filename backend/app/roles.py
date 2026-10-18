"""Who gets which role, and how (CIA-48). Code only; the model never decides access.

- Self sign-up: a new person with no admin pre-registration and no pending invite gets their
  own patient profile and the `patient` role on it.
- Admin pre-registration (phone + role + patient): applied when that phone signs up.
- Caregivers invite family only; only caregivers create patients.
- Admins list people and assign roles. Being admin opens no clinical data.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Invite,
    InviteStatus,
    Patient,
    PatientAccess,
    Person,
    PreRegistration,
    Role,
    RoleChange,
)

ADMIN = "admin"
# Roles that always belong to a patient in a pre-registration; caregiver may omit it.
NEEDS_PATIENT = {Role.family.value, Role.doctor.value, Role.nurse.value, Role.institution.value}
NO_PATIENT = {ADMIN, Role.patient.value}
PRE_REGISTRATION_ROLES = {r.value for r in Role} | {ADMIN}


def is_admin(person: Person | None) -> bool:
    return bool(person and person.is_admin)


def is_caregiver(session: Session, person: Person) -> bool:
    """Granted by an admin without a patient, or caregiver of at least one patient."""
    if person.is_caregiver:
        return True
    return session.scalar(
        select(PatientAccess.id).where(PatientAccess.person_id == person.id,
                                       PatientAccess.role == Role.caregiver).limit(1)
    ) is not None


def memberships(session: Session, person_id: str) -> list[dict]:
    rows = session.execute(
        select(PatientAccess, Patient).join(Patient, PatientAccess.patient_id == Patient.id)
        .where(PatientAccess.person_id == person_id).order_by(Patient.display_name, Patient.id)
    )
    return [{"patient_id": p.id, "patient_name": p.display_name, "role": a.role.value} for a, p in rows]


def person_state(session: Session, person: Person) -> dict:
    """What an admin sees about a person, and what a 409 shows before an overwrite."""
    return {
        "id": person.id,
        "name": person.display_name,
        "phone": person.phone,
        "is_admin": bool(person.is_admin),
        "is_caregiver": bool(person.is_caregiver),
        "memberships": memberships(session, person.id),
    }


def pre_registration_state(session: Session, pre: PreRegistration) -> dict:
    patient = session.get(Patient, pre.patient_id) if pre.patient_id else None
    return {
        "id": pre.id,
        "phone": pre.phone,
        "role": pre.role,
        "patient_id": pre.patient_id,
        "patient_name": patient.display_name if patient else None,
        "created_at": pre.created_at,
    }


def log(session: Session, action: str, *, actor_id: str | None, person_id: str | None = None,
        phone: str | None = None, patient_id: str | None = None,
        before: dict | None = None, after: dict | None = None) -> None:
    session.add(RoleChange(actor_id=actor_id, action=action, person_id=person_id, phone=phone,
                           patient_id=patient_id, before=before, after=after))


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


def apply_role(session: Session, person: Person, role: str, patient_id: str | None) -> None:
    """Give an existing person a role from a pre-registration (or an admin's confirmed change).

    Callers validate and confirm first (an admin role on an existing person needs confirmation).
    """
    if role == ADMIN:
        person.is_admin = True
    elif role == Role.patient.value and patient_id is None:
        own_patient_profile(session, person)
    elif role == Role.caregiver.value and patient_id is None:
        person.is_caregiver = True
    else:
        set_membership(session, person, patient_id, Role(role))
    session.flush()


def on_signup(session: Session, person: Person) -> str:
    """Decide a brand-new person's starting role. Returns what was applied (for logs and tests).

    Pre-registration first (it is the admin's explicit decision); a pending family invite
    stays to be accepted in the app; otherwise the person signed up for themselves: patient.
    """
    pre = session.scalar(select(PreRegistration).where(PreRegistration.phone == person.phone))
    if pre is not None:
        apply_role(session, person, pre.role, pre.patient_id)
        log(session, "pre_registration_applied", actor_id=pre.created_by, person_id=person.id,
            phone=person.phone, patient_id=pre.patient_id,
            after={"role": pre.role, "patient_id": pre.patient_id})
        session.delete(pre)
        return f"pre_registration:{pre.role}"
    invited = session.scalar(select(Invite.id).where(Invite.phone == person.phone,
                                                     Invite.status == InviteStatus.pending).limit(1))
    if invited is not None:
        return "invite_pending"
    own_patient_profile(session, person)
    return "self_signup_patient"
