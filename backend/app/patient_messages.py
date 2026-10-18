"""Patient messages (AGENTS.md 6-7, docs/contract.md "Patient messages"; CIA-29).

The patient has two actions:
- "I need help" (`help`): a fixed rule. The team is notified right away; the model is never called.
- "How I feel" (`feeling`, text or audio): audio is transcribed, then the text goes through the
  same triage as every message. The team is always notified (CIA-60); if the model says
  emergency, with the same urgent wording as for help.

What the patient reads back is fixed text written here, never model output. The team is every
caregiver and health-team member of the patient (models.patient_team): web inbox (notify.py).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import notify, triage as triage_mod
from app.deps import PatientContext, current_person_id, get_db, patient_access
from app.errors import error_response
from app.models import (
    Patient,
    PatientMessage,
    PatientMessageKind,
    PatientMessageSeen,
    Permission,
    Role,
    can,
    role_for,
    utcnow,
)
from app.transcribe import TranscriptionError, transcribe
from app.web_reports import AUDIO_TYPES, MAX_AUDIO_BYTES

log = logging.getLogger(__name__)

router = APIRouter(tags=["patient-messages"])

MAX_TEXT_CHARS = 1000

HELP_MESSAGE = "Ya avisamos a tu equipo. Si es una emergencia, llamá a emergencias."
RED_FLAG_MESSAGE = "Avisamos a tu equipo. Si es una emergencia, llamá a emergencias o a tu médico ahora."
FEELING_MESSAGE = "Gracias, tu equipo va a ver tu mensaje. Si es una emergencia, llamá a emergencias."
FEELING_TRIAGE_FAILED_MESSAGE = "Gracias, tu equipo va a ver tu mensaje. " + triage_mod.TRIAGE_FAILED_LINE
# A patient who signed up alone has nobody to notify yet (CIA-48): never claim "we told your team".
NO_TEAM_MESSAGE = "Todavía no hay nadie en tu equipo para avisar. Si es una emergencia, llamá a emergencias ahora."


@router.post("/patients/{patient_id}/patient-messages")
async def create_patient_message(
    patient_id: str,
    request: Request,
    person_id: str = Depends(current_person_id),
    db: Session = Depends(get_db),
):
    role = role_for(db, person_id, patient_id) if db.get(Patient, patient_id) is not None else None
    if role is None:
        return error_response(404, "not_found", "No encontramos a ese paciente.")
    if not can(db, person_id, patient_id, Permission.send_patient_message):
        return error_response(403, "forbidden", "Tu rol no permite enviar mensajes como paciente.")

    content_type = request.headers.get("content-type", "")
    audio = None
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        kind, text, audio = form.get("kind"), None, form.get("audio")
        if audio is None or isinstance(audio, str):
            return error_response(400, "audio_missing", "Falta el archivo de audio.")
    elif content_type.startswith("application/json"):
        try:
            body = json.loads(await request.body())
        except ValueError:
            return error_response(400, "invalid_json", "El cuerpo no es JSON válido.")
        if not isinstance(body, dict):
            return error_response(400, "invalid_json", "El cuerpo no es JSON válido.")
        kind, text = body.get("kind"), body.get("text")
    else:
        return error_response(415, "unsupported_media_type", "Enviá JSON con `kind` o un formulario con `audio`.")

    if kind not in (PatientMessageKind.help.value, PatientMessageKind.feeling.value):
        return error_response(400, "invalid_kind", "`kind` tiene que ser `feeling` o `help`.")
    kind = PatientMessageKind(kind)

    message = PatientMessage(patient_id=patient_id, sender_id=person_id, kind=kind)
    if kind is PatientMessageKind.help:
        # Fixed rule: no transcription, no model, nothing that can fail before the team hears.
        reply = HELP_MESSAGE
    else:
        if audio is not None:
            mime = (audio.content_type or "").split(";")[0].strip()
            if mime not in AUDIO_TYPES:
                return error_response(415, "unsupported_audio", "Formato de audio no soportado. Usá webm, ogg o m4a.")
            data = await audio.read()
            if not data:
                return error_response(400, "audio_empty", "El audio llegó vacío. Grabalo de nuevo.")
            if len(data) > MAX_AUDIO_BYTES:
                return error_response(413, "audio_too_large", "El audio es demasiado largo. Grabá un mensaje más corto.")
            try:
                result = await run_in_threadpool(transcribe, data, filename=AUDIO_TYPES[mime], mime_type=mime)
            except TranscriptionError as exc:
                log.error("Patient message for %s: transcription failed: %s", patient_id, exc)
                return error_response(
                    502, "transcription_failed",
                    "No pudimos entender el audio. Probá de nuevo o escribilo. Si es una emergencia, llamá a emergencias.",
                )
            text, message.from_audio = result.text, True
        if not isinstance(text, str) or not text.strip():
            return error_response(400, "text_missing", "Contanos cómo te sentís.")
        if len(text) > MAX_TEXT_CHARS:
            return error_response(400, "text_too_long", "El mensaje es demasiado largo.")
        message.text = text.strip()
        # Same triage as every message (never raises; failure is visible to the patient).
        result = await run_in_threadpool(triage_mod.triage, message.text, sender_role=role)
        message.red_flag = result.emergency
        message.triage_status = result.status
        message.triage_reason, message.triage_quote = result.reason, result.quote
        message.triage_quote_verified, message.triage_model = result.quote_verified, result.model
        if result.emergency:
            reply = RED_FLAG_MESSAGE
        elif result.status.value == "failed":
            reply = FEELING_TRIAGE_FAILED_MESSAGE
        else:
            reply = FEELING_MESSAGE

    db.add(message)
    db.flush()  # assigns message.id for the notification rows
    # Every message reaches the team (CIA-60); help and red flags get the urgent wording.
    notified = notify.notify_patient_team(db, message)
    if not notified:
        reply = NO_TEAM_MESSAGE
    db.commit()
    log.info("Patient message %s stored kind=%s red_flag=%s notified=%d",
             message.id, kind.value, message.red_flag, len(notified))
    return {"id": message.id, "kind": kind.value, "notified": notified,
            "red_flag": message.red_flag, "message_for_patient": reply}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive UTC


def mark_seen(db: Session, message_ids: list[str], person_id: str) -> None:
    """Record that `person_id` saw these messages. Race-safe: the web polls every few seconds,
    so two overlapping requests may insert the same pair; the duplicate is skipped, never a 500."""
    if not message_ids:
        return
    dialect = postgresql if db.get_bind().dialect.name == "postgresql" else sqlite
    rows = [{"patient_message_id": m, "person_id": person_id, "seen_at": utcnow()} for m in message_ids]
    db.execute(dialect.insert(PatientMessageSeen).values(rows)
               .on_conflict_do_nothing(index_elements=["patient_message_id", "person_id"]))
    db.commit()


@router.get("/patients/{patient_id}/patient-messages")
def list_patient_messages(
    limit: int = Query(50, ge=1, le=100),
    ctx: PatientContext = Depends(patient_access(Permission.read_patient_messages)),
    db: Session = Depends(get_db),
) -> dict:
    """Latest first. A team member listing the messages marks them as seen by them."""
    messages = db.scalars(
        select(PatientMessage)
        .where(PatientMessage.patient_id == ctx.patient.id)
        .order_by(PatientMessage.created_at.desc(), PatientMessage.id.desc())
        .limit(limit)
    ).all()
    if ctx.role is not Role.patient:
        new = [m for m in messages if all(s.person_id != ctx.person_id for s in m.seen)]
        mark_seen(db, [m.id for m in new], ctx.person_id)
        for m in new:
            db.refresh(m)
    return {"messages": [
        {"id": m.id, "kind": m.kind.value, "text": m.text, "red_flag": m.red_flag,
         "reason": m.triage_reason if m.red_flag else None, "created_at": _aware(m.created_at),
         "seen_by": [{"user_id": s.person_id, "name": s.person.display_name if s.person else ""} for s in m.seen]}
        for m in messages
    ]}
