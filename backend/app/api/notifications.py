"""Web notification inbox for the caller (emergency alerts addressed to them).

GET /me/notifications?since=<iso>&unread_only=false&limit=50, POST /me/notifications/{id}/read,
POST /me/notifications/read-all. A person only ever sees their own `web` rows.
MVP note: access to the patient is not re-checked on read; if access is revoked,
rows already addressed to the person stay visible to them.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import schemas, serializers
from app.deps import current_person_id, get_db
from app.errors import api_error
from app.models import Notification, NotificationChannel, Patient, utcnow

router = APIRouter(tags=["notifications"])


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive UTC


def _mine(person_id: str):
    return (Notification.person_id == person_id, Notification.channel == NotificationChannel.web.value)


def _serialize(db: Session, n: Notification) -> dict:
    patient = db.get(Patient, n.patient_id)
    return serializers.serialize_notification(n, patient.display_name if patient else "")


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
def read_all(person_id: str = Depends(current_person_id), db: Session = Depends(get_db)):
    result = db.execute(
        update(Notification).where(*_mine(person_id), Notification.read_at.is_(None)).values(read_at=utcnow())
    )
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
