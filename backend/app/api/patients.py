"""Patient read routes: GET /patients/{id}, /patients/{id}/reports, /patients/{id}/alerts.

See docs/backend-routes-plan.md. Read-only; permissions via `patient_access`.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import schemas
from app.deps import PatientContext, get_db, patient_access
from app.models import Alert, Permission, Report, ReportVersion
from app.serializers import serialize_alert, serialize_patient, serialize_report

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
