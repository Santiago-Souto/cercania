"""Web notification inbox for the caller (emergency alerts addressed to them).

GET /me/notifications?since=<iso>&unread_only=false&limit=50, POST /me/notifications/{id}/read,
POST /me/notifications/read-all[?patient_id=&urgent=]. A person only ever sees their own `web` rows.
MVP note: access to the patient is not re-checked on read; if access is revoked,
rows already addressed to the person stay visible to them.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app import notify, schemas, serializers
from app.deps import current_person_id, get_db
from app.errors import api_error
from app.models import (
    Notification,
    NotificationChannel,
    Patient,
    PatientMessage,
    PatientMessageKind,
    TriageStatus,
    utcnow,
)

router = APIRouter(tags=["notifications"])


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive UTC


def _mine(person_id: str):
    return (Notification.person_id == person_id, Notification.channel == NotificationChannel.web.value)


def _serialize(db: Session, n: Notification) -> dict:
    patient = db.get(Patient, n.patient_id)
    message = db.get(PatientMessage, n.patient_message_id) if n.patient_message_id else None
    return serializers.serialize_notification(n, patient.display_name if patient else "",
                                              urgent=notify.is_urgent(n, message))


@router.get("/me/notifications", response_model=schemas.NotificationsPage)
def list_notifications(
    since: datetime | None = None,
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    person_id: str = Depends(current_person_id),
    db: Session = Depends(get_db),
):
    unread_count = db.scalar(
        select(func.count()).select_from(Notification).where(*_mine(person_id), Notification.read_at.is_(None))
    )
    query = select(Notification).where(*_mine(person_id))
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if since is not None:
        query = query.where(Notification.created_at > _aware(since).astimezone(timezone.utc))
    rows = db.scalars(query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)).all()
    return {"notifications": [_serialize(db, n) for n in rows], "unread_count": unread_count or 0}


@router.post("/me/notifications/read-all")
def read_all(patient_id: str | None = None, urgent: bool | None = None,
             person_id: str = Depends(current_person_id), db: Session = Depends(get_db)):
    """All of the caller's unread rows, or only one patient's.

    `urgent=false` keeps emergencies, help, red flags and failed triage unread: opening a patient
    clears its plain "how I feel" news, never an urgent row the watcher has not announced yet.
    The rule mirrors `notify.is_urgent`.
    """
    where = [*_mine(person_id), Notification.read_at.is_(None)]
    if patient_id is not None:
        where.append(Notification.patient_id == patient_id)
    if urgent is not None:
        plain = select(PatientMessage.id).where(
            PatientMessage.kind == PatientMessageKind.feeling,
            PatientMessage.red_flag.is_(False),
            or_(PatientMessage.triage_status.is_(None), PatientMessage.triage_status != TriageStatus.failed),
        )
        in_plain = Notification.patient_message_id.in_(plain)
        where.append(~in_plain | Notification.patient_message_id.is_(None) if urgent else in_plain)
    result = db.execute(update(Notification).where(*where).values(read_at=utcnow()))
    db.commit()
    return {"updated": result.rowcount}


@router.post("/me/notifications/{notification_id}/read", response_model=schemas.Notification)
def mark_read(notification_id: str, person_id: str = Depends(current_person_id), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if n is None or n.person_id != person_id or n.channel != NotificationChannel.web.value:
        raise api_error(404, "not_found", "No encontramos esa notificación.")
    if n.read_at is None:
        n.read_at = utcnow()
        db.commit()
    return _serialize(db, n)
