"""Admin routes (CIA-48): list people and assign roles. Nothing else.

Admins are a global flag on the person (`person.is_admin`): set by hand in the database, from an
admin pre-registration at sign-up, or by another admin on an existing person (with confirmation).
Being admin opens no patient, report, alert, care-plan or message route: those still need a
membership. A change that would replace something that exists answers 409 with the current
state and is applied only when repeated with `confirm_overwrite: true`. Every change is logged
in `role_change`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import roles, schemas
from app.api.auth import normalize_phone
from app.deps import current_person_id, get_db
from app.errors import api_error
from app.models import Patient, PatientAccess, Person, PreRegistration, Role

router = APIRouter(tags=["admin"])


def require_admin(person_id: str = Depends(current_person_id), db: Session = Depends(get_db)) -> str:
    if not roles.is_admin(db.get(Person, person_id)):
        raise api_error(403, "forbidden", "Solo una persona administradora puede hacer esto.")
    return person_id


def _overwrite(message: str, current: dict) -> Exception:
    exc = api_error(409, "overwrite_required", message)
    exc.detail["current"] = jsonable_encoder(current)  # the error handler writes plain JSON
    return exc


def _check_role_and_patient(db: Session, role: str, patient_id: str | None) -> None:
    if role in roles.NEEDS_PATIENT and not patient_id:
        raise api_error(422, "patient_required", "Elegí el paciente para este rol.")
    if role in roles.NO_PATIENT and patient_id:
        raise api_error(422, "patient_not_used", "Este rol no va asociado a un paciente.")
    if patient_id and db.get(Patient, patient_id) is None:
        raise api_error(404, "not_found", "No encontramos a ese paciente.")


@router.get("/admin/people")
def list_people(admin_id: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Every person with their roles, pending pre-registrations, and the patients to pick from
    (names only: an admin never sees clinical data)."""
    people = db.scalars(select(Person).order_by(Person.display_name, Person.id)).all()
    pres = db.scalars(select(PreRegistration).order_by(PreRegistration.created_at, PreRegistration.id)).all()
    patients = db.scalars(select(Patient).order_by(Patient.display_name, Patient.id)).all()
    return {
        "people": [roles.person_state(db, p) for p in people],
        "pre_registrations": [roles.pre_registration_state(db, p) for p in pres],
        "patients": [{"id": p.id, "display_name": p.display_name} for p in patients],
    }


@router.put("/admin/people/{person_id}/memberships/{patient_id}")
def set_membership(person_id: str, patient_id: str, body: schemas.AdminMembershipIn,
                   admin_id: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Give a person a role on a patient. Replacing their current role there needs confirmation."""
    person = db.get(Person, person_id)
    if person is None:
        raise api_error(404, "not_found", "No encontramos a esa persona.")
    if db.get(Patient, patient_id) is None:
        raise api_error(404, "not_found", "No encontramos a ese paciente.")
    if body.role == Role.patient.value and roles.other_patient_login(db, patient_id, person_id):
        raise api_error(409, "patient_has_login", roles.PATIENT_HAS_LOGIN)  # one own login per patient
    access = db.scalar(select(PatientAccess).where(PatientAccess.person_id == person_id,
                                                   PatientAccess.patient_id == patient_id))
    before = {"role": access.role.value} if access else None
    if access is not None and access.role.value != body.role and not body.confirm_overwrite:
        raise _overwrite("Esta persona ya tiene otro rol con este paciente.", roles.person_state(db, person))
    if before != {"role": body.role}:
        roles.set_membership(db, person, patient_id, Role(body.role))
        roles.log(db, "membership_set", actor_id=admin_id, person_id=person_id, patient_id=patient_id,
                  before=before, after={"role": body.role})
        db.commit()
    return roles.person_state(db, person)


@router.put("/admin/people/{person_id}/admin")
def make_admin(person_id: str, body: schemas.MakeAdminIn, admin_id: str = Depends(require_admin),
               db: Session = Depends(get_db)) -> dict:
    """Another admin makes an existing person an admin. Always confirmed first: the 409 shows who
    they are and their current roles. Their memberships stay as they are."""
    person = db.get(Person, person_id)
    if person is None:
        raise api_error(404, "not_found", "No encontramos a esa persona.")
    if person.is_admin:
        return roles.person_state(db, person)
    if not body.confirm_overwrite:
        raise _overwrite("Vas a hacer administradora a una persona que ya está registrada.", roles.person_state(db, person))
    before = roles.person_state(db, person)
    person.is_admin = True
    roles.log(db, "admin_granted", actor_id=admin_id, person_id=person.id, before=before, after={"is_admin": True})
    db.commit()
    return roles.person_state(db, person)


@router.delete("/admin/people/{person_id}/memberships/{patient_id}")
def remove_membership(person_id: str, patient_id: str, admin_id: str = Depends(require_admin),
                      db: Session = Depends(get_db)) -> dict:
    person = db.get(Person, person_id)
    access = db.scalar(select(PatientAccess).where(PatientAccess.person_id == person_id,
                                                   PatientAccess.patient_id == patient_id))
    if person is None or access is None:
        raise api_error(404, "not_found", "Esa persona no tiene un rol con ese paciente.")
    roles.log(db, "membership_removed", actor_id=admin_id, person_id=person_id, patient_id=patient_id,
              before={"role": access.role.value})
    db.delete(access)
    db.commit()
    return roles.person_state(db, person)


@router.post("/admin/pre-registrations", status_code=201)
def pre_register(body: schemas.PreRegistrationIn, response: Response,
                 admin_id: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Phone + role (+ patient) for someone who has not signed up. Nothing is sent.

    - The phone already belongs to a person: 409 with that person; confirmed, the role is applied
      to them now (`admin` makes them an admin).
    - The phone already has a pre-registration: 409 with it; confirmed, it is replaced.
    """
    phone = normalize_phone(body.phone)
    _check_role_and_patient(db, body.role, body.patient_id)

    person = db.scalar(select(Person).where(Person.phone == phone))
    if person is not None:
        if not body.confirm_overwrite:
            raise _overwrite("Este número ya es de una persona registrada.", {"person": roles.person_state(db, person)})
        before = roles.person_state(db, person)
        roles.apply_role(db, person, body.role, body.patient_id)
        roles.log(db, "role_applied", actor_id=admin_id, person_id=person.id, phone=phone,
                  patient_id=body.patient_id, before=before, after={"role": body.role, "patient_id": body.patient_id})
        db.commit()
        response.status_code = 200
        return {"applied_to": roles.person_state(db, person)}

    pre = db.scalar(select(PreRegistration).where(PreRegistration.phone == phone))
    if pre is not None:
        if not body.confirm_overwrite:
            raise _overwrite("Este número ya tiene un rol pendiente de registro.",
                             {"pre_registration": roles.pre_registration_state(db, pre)})
        before = {"role": pre.role, "patient_id": pre.patient_id}
        pre.role, pre.patient_id, pre.created_by = body.role, body.patient_id, admin_id
        response.status_code = 200
    else:
        before = None
        pre = PreRegistration(phone=phone, role=body.role, patient_id=body.patient_id, created_by=admin_id)
        db.add(pre)
    roles.log(db, "pre_registration_set", actor_id=admin_id, phone=phone, patient_id=body.patient_id,
              before=before, after={"role": body.role, "patient_id": body.patient_id})
    db.commit()
    return {"pre_registration": roles.pre_registration_state(db, pre)}


@router.patch("/admin/pre-registrations/{pre_id}")
def edit_pre_registration(pre_id: str, body: schemas.PreRegistrationPatch,
                          admin_id: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    pre = db.get(PreRegistration, pre_id)
    if pre is None:
        raise api_error(404, "not_found", "No encontramos ese registro pendiente.")
    _check_role_and_patient(db, body.role, body.patient_id)
    before = {"role": pre.role, "patient_id": pre.patient_id}
    pre.role, pre.patient_id = body.role, body.patient_id
    roles.log(db, "pre_registration_set", actor_id=admin_id, phone=pre.phone, patient_id=body.patient_id,
              before=before, after={"role": body.role, "patient_id": body.patient_id})
    db.commit()
    return {"pre_registration": roles.pre_registration_state(db, pre)}


@router.delete("/admin/pre-registrations/{pre_id}")
def delete_pre_registration(pre_id: str, admin_id: str = Depends(require_admin),
                            db: Session = Depends(get_db)) -> dict:
    pre = db.get(PreRegistration, pre_id)
    if pre is None:
        raise api_error(404, "not_found", "No encontramos ese registro pendiente.")
    roles.log(db, "pre_registration_deleted", actor_id=admin_id, phone=pre.phone, patient_id=pre.patient_id,
              before={"role": pre.role, "patient_id": pre.patient_id})
    db.delete(pre)
    db.commit()
    return {"status": "deleted"}
