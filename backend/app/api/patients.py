"""Patient routes: reads (GET /patients/{id}, /reports, /alerts) and the team
(POST /patients, DELETE /patients/{id}, PATCH /patients/{id}/emergency-contact, GET /patients/{id}/members, POST /patients/{id}/invites).

See docs/contract.md. Permissions via `patient_access`.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import roles, schemas
from app.api.auth import normalize_phone
from app.deps import PatientContext, _authorize, current_person_id, get_db, patient_access
from app.errors import api_error
from app.models import (
    Alert,
    CarePlan,
    Invite,
    InviteStatus,
    Medication,
    Patient,
    PatientAccess,
    Permission,
    Person,
    Report,
    ReportVersion,
    ROLE_PERMISSIONS,
    Role,
)
from app.serializers import serialize_alert, serialize_invite, serialize_patient, serialize_report

log = logging.getLogger(__name__)

router = APIRouter(tags=["patients"])


class AlertsPage(BaseModel):
    alerts: list[schemas.Alert]


def as_utc(value: datetime) -> datetime:
    """Naive datetimes (SQLite, or a client that omits the offset) are taken as UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@router.get("/patients/{patient_id}", response_model=schemas.Patient)
def get_patient(
    ctx: PatientContext = Depends(patient_access(Permission.read_care_plan)),
    db: Session = Depends(get_db),
) -> dict:
    return serialize_patient(db, ctx.patient)


@router.get("/patients/{patient_id}/reports", response_model=schemas.ReportsPage)
def list_reports(
    limit: int = Query(20, ge=1, le=100),
    before: datetime | None = None,
    ctx: PatientContext = Depends(patient_access(Permission.read_reports)),
    db: Session = Depends(get_db),
) -> dict:
    """Newest first. `next_before` is the created_at of the last report returned when more may exist."""
    stmt = (
        select(Report)
        .where(Report.patient_id == ctx.patient.id)
        .options(
            selectinload(Report.versions).selectinload(ReportVersion.items),
            selectinload(Report.versions).selectinload(ReportVersion.alerts),
            selectinload(Report.sender),
            selectinload(Report.files),
        )
        .order_by(Report.created_at.desc(), Report.id.desc())
        .limit(limit + 1)
    )
    if before is not None:
        stmt = stmt.where(Report.created_at < as_utc(before))
    rows = list(db.scalars(stmt))
    page = rows[:limit]
    next_before = page[-1].created_at if len(rows) > limit else None
    return {"reports": [serialize_report(db, r) for r in page], "next_before": next_before}


@router.get("/patients/{patient_id}/alerts", response_model=AlertsPage)
def list_alerts(
    since: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    ctx: PatientContext = Depends(patient_access(Permission.read_reports)),
    db: Session = Depends(get_db),
) -> dict:
    """Alerts on the latest version of each of the patient's reports, newest first."""
    latest = (
        select(ReportVersion.report_id, func.max(ReportVersion.version).label("v"))
        .group_by(ReportVersion.report_id)
        .subquery()
    )
    stmt = (
        select(Alert)
        .join(ReportVersion, Alert.report_version_id == ReportVersion.id)
        .join(Report, ReportVersion.report_id == Report.id)
        .join(latest, (latest.c.report_id == ReportVersion.report_id) & (latest.c.v == ReportVersion.version))
        .where(Report.patient_id == ctx.patient.id)
        .options(selectinload(Alert.report_version).selectinload(ReportVersion.report))
        .order_by(Alert.created_at.desc(), Alert.id.desc())
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(Alert.created_at > as_utc(since))
    return {"alerts": [serialize_alert(a) for a in db.scalars(stmt)]}


def _emergency_phone(raw: str) -> str:
    """Same normalization as other phones; a bad number is a 422 here (it is a body field)."""
    try:
        return normalize_phone(raw)
    except HTTPException as exc:
        raise api_error(422, "phone_invalid", exc.detail["message"]) from exc


def _patient_phone(db: Session, caregiver: Person, raw: str) -> str:
    """The patient's own phone: one live patient per phone, and never the caregiver's own."""
    phone = _emergency_phone(raw)
    if phone == caregiver.phone:
        raise api_error(422, "patient_phone_self", "Ese es tu número. Escribí el celular del paciente.")
    taken = db.scalar(select(Patient.id).where(Patient.phone == phone, Patient.archived_at.is_(None)).limit(1))
    if taken is not None:
        raise api_error(409, "patient_phone_taken", "Ese celular ya está asociado a otro paciente.")
    return phone


@router.post("/patients", response_model=schemas.Patient, status_code=201)
def create_patient(
    body: schemas.PatientCreate,
    person_id: str = Depends(current_person_id),
    db: Session = Depends(get_db),
) -> dict:
    """The creator becomes the patient's caregiver and sets care plan v1. An optional `phone`
    (the patient's own cell) lets that person join as the patient's login when they sign up.

    Doses are stored as typed (AGENTS.md 7). Only caregivers add patients (CIA-48): a caregiver
    membership on any patient, or a caregiver an admin registered before assigning patients.
    """
    person = db.get(Person, person_id)
    if person is None:
        raise api_error(401, "unauthenticated", "Iniciá sesión para continuar.")
    if not roles.is_caregiver(db, person):
        raise api_error(403, "forbidden", "Solo las personas cuidadoras pueden agregar pacientes.")
    phone = _patient_phone(db, person, body.phone) if body.phone else None
    patient = Patient(display_name=body.display_name, location=body.location or None, phone=phone)
    if body.emergency_contact is not None:
        patient.health_provider_name = body.emergency_contact.name
        patient.health_provider_phone = _emergency_phone(body.emergency_contact.phone)
    db.add(patient)
    db.flush()
    plan = CarePlan(patient_id=patient.id, version=1, created_by=person_id,
                    indications=list(body.care_plan.indications), allergies=list(body.care_plan.allergies))
    db.add(plan)
    db.flush()
    for m in body.care_plan.medications:
        db.add(Medication(care_plan_id=plan.id, name=m.name, dose_text=m.dose, times=list(m.times)))
    db.add(PatientAccess(person_id=person_id, patient_id=patient.id, role=Role.caregiver))
    if phone and db.scalar(select(Person.id).where(Person.phone == phone)) is not None:
        # Already has an account, so sign-up will not link them: they get a patient invite to accept
        # (accepting folds their self sign-up profile into this one). Same answer either way.
        db.add(Invite(patient_id=patient.id, phone=phone, role=Role.patient, invited_by=person_id))
    db.commit()
    return serialize_patient(db, patient)


@router.patch("/patients/{patient_id}/emergency-contact", response_model=schemas.Patient)
async def set_emergency_contact(
    request: Request,
    ctx: PatientContext = Depends(patient_access(Permission.edit_emergency_contact)),
    db: Session = Depends(get_db),
) -> dict:
    """Set or clear (`null`) the number the app offers to call on an emergency. Only stored:
    the server never calls or texts it (AGENTS.md 4.2). The body is read by hand because
    FastAPI treats a JSON `null` body as missing."""
    try:
        raw = await request.json()
        body = None if raw is None else schemas.EmergencyContactIn.model_validate(raw)
    except (ValueError, ValidationError) as exc:
        raise api_error(422, "invalid_request", "Revisá los datos enviados.") from exc
    if body is None:
        ctx.patient.health_provider_name = None
        ctx.patient.health_provider_phone = None
    else:
        ctx.patient.health_provider_phone = _emergency_phone(body.phone)
        ctx.patient.health_provider_name = body.name
    db.commit()
    return serialize_patient(db, ctx.patient)


@router.delete("/patients/{patient_id}", response_model=schemas.PatientArchived)
def archive_patient(
    ctx: PatientContext = Depends(patient_access(Permission.archive_patient)),
    db: Session = Depends(get_db),
) -> dict:
    """A caregiver removes the patient: soft delete. Nobody keeps access and pending invites are
    dropped; reports and their versions stay stored (evidence trail), never shown again."""
    roles.archive_patient(db, ctx.patient, ctx.person_id)
    db.commit()
    return {"status": "archived"}


@router.get("/patients/{patient_id}/members", response_model=schemas.Members)
def list_members(
    ctx: PatientContext = Depends(patient_access(Permission.read_reports)),
    db: Session = Depends(get_db),
) -> dict:
    """Everyone with access, plus pending invites. Invited phone numbers are shown only to
    roles that can invite (caregivers); others get an empty `invites` list."""
    rows = db.execute(
        select(PatientAccess, Person)
        .join(Person, PatientAccess.person_id == Person.id)
        .where(PatientAccess.patient_id == ctx.patient.id)
        .order_by(PatientAccess.id)
    )
    members = [{"user_id": p.id, "name": p.display_name, "role": a.role.value} for a, p in rows]
    invites = []
    if Permission.invite in ROLE_PERMISSIONS[ctx.role]:
        invites = [serialize_invite(i) for i in db.scalars(
            select(Invite)
            .where(Invite.patient_id == ctx.patient.id, Invite.status == InviteStatus.pending)
            .order_by(Invite.created_at, Invite.id)
        )]
    return {"members": members, "invites": invites}


def _pending_invite(db: Session, patient_id: str | None, phone: str, inviter_id: str | None = None) -> Invite | None:
    stmt = select(Invite).where(Invite.phone == phone, Invite.status == InviteStatus.pending)
    if patient_id is None:  # a new-patient invite: one pending per inviter and phone
        stmt = stmt.where(Invite.patient_id.is_(None), Invite.invited_by == inviter_id)
    else:
        stmt = stmt.where(Invite.patient_id == patient_id)
    return db.scalar(stmt)


INVITE_ROLES = {Role.family.value, Role.patient.value}


def _invite(db: Session, response: Response, inviter_id: str, patient_id: str | None, contact: str, role_name: str) -> dict:
    """Family or patient invite (CIA-48). It becomes `patient_access` only when the person with
    that phone accepts it in the app (api/me.py `accept_invite`). Re-inviting a pending number
    updates its role instead of adding a second invite."""
    if role_name not in INVITE_ROLES:
        raise api_error(422, "invite_role", "Se invita como familiar o como paciente. Los demás roles los asigna una persona administradora.")
    if "@" in contact:
        raise api_error(400, "phone_invalid",
                        "Invitá por número de celular, no por email: el email no se puede verificar.")
    phone = normalize_phone(contact)
    role = Role(role_name)
    if patient_id is not None:
        already = db.scalar(
            select(PatientAccess.id)
            .join(Person, PatientAccess.person_id == Person.id)
            .where(PatientAccess.patient_id == patient_id, Person.phone == phone)
        )
        if already is not None:
            raise api_error(409, "already_member", "Esa persona ya tiene acceso a este paciente.")
        if role is Role.patient and roles.other_patient_login(db, patient_id, None):
            raise api_error(409, "patient_has_login", roles.PATIENT_HAS_LOGIN)
    elif roles.has_own_profile(db, db.scalar(select(Person).where(Person.phone == phone))):
        # A profile-less patient invite is for someone with no profile yet: never a way into an
        # existing person's profile (it would make the inviter their caregiver).
        raise api_error(409, "profile_exists", roles.PROFILE_EXISTS)
    invite = _pending_invite(db, patient_id, phone, inviter_id)
    created = invite is None
    if created:
        invite = Invite(patient_id=patient_id, phone=phone, role=role, invited_by=inviter_id)
        db.add(invite)
        try:
            db.commit()
        except IntegrityError:
            # A concurrent request inserted the pending invite first (uq_invite_pending): update that one.
            db.rollback()
            invite = _pending_invite(db, patient_id, phone, inviter_id)
            if invite is None:
                raise
            created = False
    if not created:
        invite.role = role
        db.commit()
        response.status_code = 200
    return serialize_invite(invite)


@router.post("/patients/{patient_id}/invites", response_model=schemas.Invite, status_code=201)
def create_invite(
    body: schemas.InviteCreate,
    response: Response,
    ctx: PatientContext = Depends(patient_access(Permission.invite)),
    db: Session = Depends(get_db),
) -> dict:
    """A caregiver invites someone to this patient: as family, or as the patient's own login."""
    return _invite(db, response, ctx.person_id, ctx.patient.id, body.contact, body.role)


@router.post("/invites", response_model=schemas.Invite, status_code=201)
def create_caregiver_invite(
    body: schemas.CaregiverInviteCreate,
    response: Response,
    person_id: str = Depends(current_person_id),
    db: Session = Depends(get_db),
) -> dict:
    """Same invite, with the patient chosen in the body. `family` needs a patient; `patient`
    without one invites someone with no profile yet: accepting creates it, with the inviting
    caregiver as its caregiver."""
    person = db.get(Person, person_id)
    if person is None:
        raise api_error(401, "unauthenticated", "Iniciá sesión para continuar.")
    if body.patient_id is not None:
        _authorize(db, person_id, body.patient_id, Permission.invite)
    elif body.role == Role.family.value:
        raise api_error(422, "patient_required", "Para invitar a un familiar, elegí el paciente.")
    elif not roles.is_caregiver(db, person):
        raise api_error(403, "forbidden", "Solo las personas cuidadoras pueden invitar.")
    return _invite(db, response, person_id, body.patient_id, body.contact, body.role)
