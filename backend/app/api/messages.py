"""Family <-> health team messages (docs/contract.md "Family <-> health team messages"; CIA-36).

GET and POST /patients/{id}/messages. One thread per patient between family and the health
team (doctor, nurse, institution); caregivers and the patient have no access. Human to human:
no model call anywhere here, and the web always shows "not for emergencies" (AGENTS.md 7).
Listing the thread marks the other people's messages as read by the caller.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session, selectinload

from app import schemas, serializers
from app.deps import PatientContext, get_db, patient_access
from app.models import Message, MessageRead, Permission, utcnow

router = APIRouter(tags=["messages"])


def _mark_read(db: Session, message_ids: list[str], person_id: str) -> None:
    """Race-safe like patient_messages.mark_seen: the web polls, so overlapping requests may
    insert the same pair; the duplicate is skipped, never a 500."""
    if not message_ids:
        return
    dialect = postgresql if db.get_bind().dialect.name == "postgresql" else sqlite
    rows = [{"message_id": m, "person_id": person_id, "read_at": utcnow()} for m in message_ids]
    db.execute(dialect.insert(MessageRead).values(rows)
               .on_conflict_do_nothing(index_elements=["message_id", "person_id"]))
    db.commit()


@router.get("/patients/{patient_id}/messages", response_model=schemas.Messages)
def list_messages(
    limit: int = Query(100, ge=1, le=200),
    ctx: PatientContext = Depends(patient_access(Permission.team_messages)),
    db: Session = Depends(get_db),
):
    """The latest `limit` messages, oldest first (thread order)."""
    latest = db.scalars(
        select(Message)
        .where(Message.patient_id == ctx.patient.id)
        .options(selectinload(Message.reads), selectinload(Message.sender))  # 3 queries per poll, not 2 per message
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    ).all()
    messages = list(reversed(latest))
    read_before = {m.id for m in messages if any(r.person_id == ctx.person_id for r in m.reads)}
    # The rows inserted here are the caller's own reads, which serialize_message never looks at.
    _mark_read(db, [m.id for m in messages if m.sender_id != ctx.person_id and m.id not in read_before],
               ctx.person_id)
    return {"messages": [serializers.serialize_message(m, ctx.person_id, read_before) for m in messages]}


@router.post("/patients/{patient_id}/messages", response_model=schemas.Message, status_code=201)
def send_message(
    body: schemas.MessageRequest,
    ctx: PatientContext = Depends(patient_access(Permission.team_messages)),
    db: Session = Depends(get_db),
):
    """Idempotent on `client_id`: a retry of a message already stored returns that message."""
    existing = _by_client_id(db, ctx, body.client_id)
    if existing is not None:
        return serializers.serialize_message(existing, ctx.person_id, set())
    message = Message(patient_id=ctx.patient.id, sender_id=ctx.person_id, sender_role=ctx.role,
                      text=body.text, client_id=body.client_id)
    db.add(message)
    try:
        db.commit()
    except IntegrityError:  # the same retry raced in between
        db.rollback()
        message = _by_client_id(db, ctx, body.client_id)
        if message is None:
            raise
    db.refresh(message)
    return serializers.serialize_message(message, ctx.person_id, set())


def _by_client_id(db: Session, ctx: PatientContext, client_id: str | None) -> Message | None:
    if client_id is None:
        return None
    return db.scalar(select(Message).where(Message.sender_id == ctx.person_id, Message.client_id == client_id,
                                           Message.patient_id == ctx.patient.id))
