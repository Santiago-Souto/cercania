"""Patient routes: reads (GET /patients/{id}, /reports, /alerts) and the team
(POST /patients, GET /patients/{id}/members, POST /patients/{id}/invites).

See docs/contract.md. Permissions via `patient_access`.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import notify, schemas, whatsapp
from app.api.auth import normalize_phone
from app.deps import PatientContext, current_person_id, get_db, patient_access
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


@router.post("/patients", response_model=schemas.Patient, status_code=201)
def create_patient(
    body: schemas.PatientCreate,
    person_id: str = Depends(current_person_id),
    db: Session = Depends(get_db),
) -> dict:
    """The creator becomes the patient's caregiver and sets care plan v1.

    Doses are stored as typed (AGENTS.md 7). Any signed-in person may add a patient:
    a new caregiver has no memberships yet, so there is no per-patient permission to check.
    """
    if db.get(Person, person_id) is None:
        raise api_error(401, "unauthenticated", "Iniciá sesión para continuar.")
    patient = Patient(display_name=body.display_name, location=body.location or None)
    db.add(patient)
    db.flush()
    plan = CarePlan(patient_id=patient.id, version=1, created_by=person_id,
                    indications=list(body.care_plan.indications), allergies=list(body.care_plan.allergies))
    db.add(plan)
    db.flush()
    for m in body.care_plan.medications:
        db.add(Medication(care_plan_id=plan.id, name=m.name, dose_text=m.dose, times=list(m.times)))
    db.add(PatientAccess(person_id=person_id, patient_id=patient.id, role=Role.caregiver))
    db.commit()
    return serialize_patient(db, patient)


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


def invite_text(inviter: str, patient: str, role: Role) -> str:
    return (f"{inviter} te invitó a CercanIA para acompañar a {patient} ({ROLE_ES[role]}). "
            "Entrá a la web de CercanIA e ingresá con este número de WhatsApp para ver su información.")


ROLE_ES = {Role.caregiver: "cuidador/a", Role.family: "familia", Role.patient: "paciente",
           Role.doctor: "médico/a", Role.nurse: "enfermería", Role.institution: "hospital o institución"}


def send_invite_whatsapp(phone: str, text: str) -> None:
    """Best effort, after the response. Off unless NOTIFY_WHATSAPP=1 (the Meta test number only
    reaches allowed-list phones); the invite works anyway when that phone logs in."""
    if not notify.whatsapp_enabled():
        log.info("Invite WhatsApp skipped for %s (NOTIFY_WHATSAPP is off)", whatsapp.mask(phone))
        return
    res = whatsapp.send_text_result(phone.lstrip("+"), text)
    if not res.ok:
        log.warning("Invite WhatsApp to %s failed: [%s] %s", whatsapp.mask(phone), res.error_code, res.error)


@router.post("/patients/{patient_id}/invites", response_model=schemas.Invite, status_code=201)
def create_invite(
    body: schemas.InviteCreate,
    background: BackgroundTasks,
    response: Response,
    ctx: PatientContext = Depends(patient_access(Permission.invite)),
    db: Session = Depends(get_db),
) -> dict:
    """Pending membership for a WhatsApp number; it becomes `patient_access` when that phone
    verifies an SMS code (api/auth.py `_accept_invites`). Re-inviting a pending number updates
    its role instead of adding a second invite."""
    if "@" in body.contact:
        raise api_error(400, "phone_invalid",
                        "Invitá por número de WhatsApp, no por email: el email no se puede verificar.")
    phone = normalize_phone(body.contact)
    role = Role(body.role)
    already = db.scalar(
        select(PatientAccess.id)
        .join(Person, PatientAccess.person_id == Person.id)
        .where(PatientAccess.patient_id == ctx.patient.id, Person.phone == phone)
    )
    if already is not None:
        raise api_error(409, "already_member", "Esa persona ya tiene acceso a este paciente.")
    invite = db.scalar(select(Invite).where(Invite.patient_id == ctx.patient.id, Invite.phone == phone,
                                            Invite.status == InviteStatus.pending))
    if invite is None:
        invite = Invite(patient_id=ctx.patient.id, phone=phone, role=role, invited_by=ctx.person_id)
        db.add(invite)
    else:
        invite.role = role
        response.status_code = 200
    db.commit()
    inviter = db.get(Person, ctx.person_id)
    background.add_task(send_invite_whatsapp, phone,
                        invite_text(inviter.display_name if inviter else "Alguien", ctx.patient.display_name, role))
    return serialize_invite(invite)
