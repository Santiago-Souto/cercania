"""Cited natural-language query route.

POST /patients/{id}/query (read_reports): question -> answer + code-verified citations.
The patient's own "how I feel" messages are included only for askers whose role may read them
(read_patient_messages: not family), and reading them here does not mark them seen (CIA-62).
Never log the question, transcripts or messages (health data); only ids, counts and timing.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import query as query_mod
from app.deps import PatientContext, get_db, patient_access
from app.errors import api_error
from app.models import Permission, PatientMessage, PatientMessageKind, Report, ReportVersion, can
from app.schemas import QueryRequest, QueryResponse

log = logging.getLogger("cercania.query")
router = APIRouter(tags=["query"])

WINDOW_DAYS = 14


def _load_reports(db: Session, patient_id: str) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    rows = db.scalars(
        select(Report)
        .where(Report.patient_id == patient_id, Report.created_at >= since)
        .options(
            selectinload(Report.versions).selectinload(ReportVersion.items),
            selectinload(Report.versions).selectinload(ReportVersion.alerts),
            selectinload(Report.sender),
        )
        .order_by(Report.created_at.desc())
        .limit(query_mod.MAX_REPORTS)
    ).all()
    out = []
    for r in rows:
        latest = r.latest
        out.append({
            "id": r.id,
            "created_at": r.created_at,
            "kind": r.kind.value,
            "sender": r.sender.display_name if r.sender else None,
            "transcript": r.transcript,
            "segments": list(r.segments or []),
            "items": [{"item": i.item.value, "value": i.value}
                      for i in (latest.items if latest else []) if i.value is not None],
            "alerts": [{"type": a.type.value, "detail": a.detail}
                       for a in (latest.alerts if latest else [])],
        })
    return out


def _load_patient_messages(db: Session, patient_id: str) -> list[dict]:
    """The patient's own "how I feel" messages with text (help requests have none to quote)."""
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    rows = db.scalars(
        select(PatientMessage)
        .where(PatientMessage.patient_id == patient_id, PatientMessage.kind == PatientMessageKind.feeling,
               PatientMessage.text.is_not(None), PatientMessage.created_at >= since)
        .order_by(PatientMessage.created_at.desc())
        .limit(query_mod.MAX_PATIENT_MESSAGES)
    ).all()
    return [{"id": m.id, "created_at": m.created_at, "text": m.text} for m in rows]


@router.post("/patients/{patient_id}/query", response_model=QueryResponse)
async def query_patient(
    body: QueryRequest,
    ctx: PatientContext = Depends(patient_access(Permission.read_reports)),
    db: Session = Depends(get_db),
) -> dict:
    reports = _load_reports(db, ctx.patient.id)
    may_read_messages = can(db, ctx.person_id, ctx.patient.id, Permission.read_patient_messages)
    messages = _load_patient_messages(db, ctx.patient.id) if may_read_messages else []
    if not reports and not messages:
        return {"answer": "Todavía no hay reportes para este paciente.", "citations": [],
                "confidence": "unclear", "note": None}
    started = time.monotonic()
    try:
        result = await run_in_threadpool(query_mod.answer_question, body.question, reports, messages)
    except query_mod.QueryError as exc:
        log.warning("query failed patient=%s reports=%d patient_messages=%d retryable=%s", ctx.patient.id,
                    len(reports), len(messages), exc.retryable)
        raise api_error(502, "query_failed", exc.message) from exc
    log.info("query patient=%s reports=%d patient_messages=%d confidence=%s citations=%d ms=%d", ctx.patient.id,
             len(reports), len(messages), result["confidence"], len(result["citations"]),
             (time.monotonic() - started) * 1000)
    return result
