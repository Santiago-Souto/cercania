"""Admin routes (CIA-48, CIA-58): list people and set each person's role. Nothing else.

An admin sets the role of a person (`person.role`) and never links people to patients: links
come from caregivers (creating a patient, inviting family or a patient's own login). Admins are a
global flag on the person (`person.is_admin`): set by hand in the database, from an admin
pre-registration at sign-up, or by another admin on an existing person (with confirmation).
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
from app.models import Person, PreRegistration

router = APIRouter(tags=["admin"])


def require_admin(person_id: str = Depends(current_person_id), db: Session = Depends(get_db)) -> str:
    if not roles.is_admin(db.get(Person, person_id)):
        raise api_error(403, "forbidden", "Solo una persona administradora puede hacer esto.")
    return person_id


def _overwrite(message: str, current: dict) -> Exception:
    exc = api_error(409, "overwrite_required", message)
    exc.detail["current"] = jsonable_encoder(current)  # the error handler writes plain JSON
    return exc


@router.get("/admin/people")
def list_people(admin_id: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Every person with their role, and pending pre-registrations. No patients: an admin never
    sees clinical data or links people to patients."""
    people = db.scalars(select(Person).order_by(Person.display_name, Person.id)).all()
    pres = db.scalars(select(PreRegistration).order_by(PreRegistration.created_at, PreRegistration.id)).all()
    return {
        "people": [roles.person_state(db, p) for p in people],
        "pre_registrations": [roles.pre_registration_state(db, p) for p in pres],
    }


@router.put("/admin/people/{person_id}/role")
def set_role(person_id: str, body: schemas.AdminRoleIn,
             admin_id: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Set a person's role. Replacing a different role needs confirmation. Leaving `patient`
    removes their login to their own profile; becoming `patient` creates it (roles.set_person_role)."""
    person = db.get(Person, person_id)
    if person is None:
        raise api_error(404, "not_found", "No encontramos a esa persona.")
    current = roles.person_role(db, person)
    if current == body.role and person.role == body.role:
        return roles.person_state(db, person)
    if current is not None and current != body.role and not body.confirm_overwrite:
        raise _overwrite("Esta persona ya tiene otro rol.", roles.person_state(db, person))
    removed = roles.set_person_role(db, person, body.role)
    after = {"role": body.role, **({"patient_logins_removed": removed} if removed else {})}
    roles.log(db, "role_set", actor_id=admin_id, person_id=person_id, before={"role": current}, after=after)
    db.commit()
    return roles.person_state(db, person)


@router.put("/admin/people/{person_id}/admin")
def make_admin(person_id: str, body: schemas.MakeAdminIn, admin_id: str = Depends(require_admin),
               db: Session = Depends(get_db)) -> dict:
    """Another admin makes an existing person an admin. Always confirmed first: the 409 shows who
    they are and their current role, which stays."""
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


@router.post("/admin/pre-registrations", status_code=201)
def pre_register(body: schemas.PreRegistrationIn, response: Response,
                 admin_id: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Phone + role for someone who has not signed up. Nothing is sent.

    - The phone already belongs to a person: 409 with that person; confirmed, the role is applied
      to them now (`admin` makes them an admin).
    - The phone already has a pre-registration: 409 with it; confirmed, it is replaced.
    """
    phone = normalize_phone(body.phone)

    person = db.scalar(select(Person).where(Person.phone == phone))
    if person is not None:
        if not body.confirm_overwrite:
            raise _overwrite("Este número ya es de una persona registrada.", {"person": roles.person_state(db, person)})
        before = roles.person_state(db, person)
        roles.apply_role(db, person, body.role)
        roles.log(db, "role_applied", actor_id=admin_id, person_id=person.id, phone=phone,
                  before=before, after={"role": body.role})
        db.commit()
        response.status_code = 200
        return {"applied_to": roles.person_state(db, person)}

    pre = db.scalar(select(PreRegistration).where(PreRegistration.phone == phone))
    if pre is not None:
        if not body.confirm_overwrite:
            raise _overwrite("Este número ya tiene un rol pendiente de registro.",
                             {"pre_registration": roles.pre_registration_state(db, pre)})
        before = {"role": pre.role}
        pre.role, pre.patient_id, pre.created_by = body.role, None, admin_id
        response.status_code = 200
    else:
        before = None
        pre = PreRegistration(phone=phone, role=body.role, created_by=admin_id)
        db.add(pre)
    roles.log(db, "pre_registration_set", actor_id=admin_id, phone=phone, before=before, after={"role": body.role})
    db.commit()
    return {"pre_registration": roles.pre_registration_state(db, pre)}


@router.patch("/admin/pre-registrations/{pre_id}")
def edit_pre_registration(pre_id: str, body: schemas.PreRegistrationPatch,
                          admin_id: str = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    pre = db.get(PreRegistration, pre_id)
    if pre is None:
        raise api_error(404, "not_found", "No encontramos ese registro pendiente.")
    before = {"role": pre.role}
    pre.role, pre.patient_id = body.role, None
    roles.log(db, "pre_registration_set", actor_id=admin_id, phone=pre.phone, before=before, after={"role": body.role})
    db.commit()
    return {"pre_registration": roles.pre_registration_state(db, pre)}


@router.delete("/admin/pre-registrations/{pre_id}")
def delete_pre_registration(pre_id: str, admin_id: str = Depends(require_admin),
                            db: Session = Depends(get_db)) -> dict:
    pre = db.get(PreRegistration, pre_id)
    if pre is None:
        raise api_error(404, "not_found", "No encontramos ese registro pendiente.")
    roles.log(db, "pre_registration_deleted", actor_id=admin_id, phone=pre.phone, before={"role": pre.role})
    db.delete(pre)
    db.commit()
    return {"status": "deleted"}
