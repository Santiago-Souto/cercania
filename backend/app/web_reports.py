"""POST /patients/{patient_id}/reports: an end-of-shift report from the web app.

Accepts JSON `{client_id, text}` or multipart `client_id` + `audio`. Audio goes
through the same transcription step as WhatsApp; then both go through
`ingest.process_report`, the same path every channel uses.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import ingest
from app.deps import current_person_id, get_db
from app.models import Patient, Permission, can
from app.transcribe import TranscriptionError, transcribe

log = logging.getLogger(__name__)

router = APIRouter()

AUDIO_TYPES = {
    "audio/webm": "voice.webm",
    "audio/ogg": "voice.ogg",
    "audio/mp4": "voice.m4a",
    "audio/m4a": "voice.m4a",
    "audio/x-m4a": "voice.m4a",
    "audio/mpeg": "voice.mp3",
    "audio/wav": "voice.wav",
    "audio/x-wav": "voice.wav",
}
# Vercel rejects request bodies over 4.5 MB before our code runs; stay under it
# so the caregiver gets our message instead of a platform error.
MAX_AUDIO_BYTES = 4 * 1024 * 1024
MAX_CLIENT_ID = 100


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@router.post("/patients/{patient_id}/reports")
async def create_report(
    patient_id: str,
    request: Request,
    person_id: str = Depends(current_person_id),
    db: Session = Depends(get_db),
):
    if db.get(Patient, patient_id) is None:
        return error(404, "not_found", "No encontramos a ese paciente.")
    if not can(db, person_id, patient_id, Permission.send_report):
        return error(403, "forbidden", "Tu rol no permite enviar reportes para este paciente.")

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        client_id, text, audio = form.get("client_id"), None, form.get("audio")
        if audio is None or isinstance(audio, str):
            return error(400, "audio_missing", "Falta el archivo de audio.")
    elif content_type.startswith("application/json"):
        try:
            body = json.loads(await request.body())
        except ValueError:
            return error(400, "invalid_json", "El cuerpo no es JSON válido.")
        if not isinstance(body, dict):
            return error(400, "invalid_json", "El cuerpo no es JSON válido.")
        client_id, text, audio = body.get("client_id"), body.get("text"), None
        if not isinstance(text, str) or not text.strip():
            return error(400, "text_missing", "El reporte está vacío. Escribí cómo estuvo el turno.")
    else:
        return error(415, "unsupported_media_type", "Enviá JSON con `text` o un formulario con `audio`.")

    if not isinstance(client_id, str) or not client_id.strip() or len(client_id) > MAX_CLIENT_ID:
        return error(400, "client_id_missing", "Falta `client_id` (o es demasiado largo).")
    message_id = ingest.web_message_id(person_id, client_id.strip())

    # A repeated client_id never transcribes again: process_report returns the stored result.
    existing = ingest.existing_report(db, message_id)
    if existing is not None and existing.patient_id != patient_id:
        return error(409, "client_id_conflict", "Ese identificador ya se usó para otro paciente. Generá uno nuevo.")
    transcript = existing.transcript if existing is not None else None
    if transcript is None and audio is not None:
        mime = (audio.content_type or "").split(";")[0].strip()
        if mime not in AUDIO_TYPES:
            return error(415, "unsupported_audio", "Formato de audio no soportado. Usá webm, ogg o m4a.")
        data = await audio.read()
        if not data:
            return error(400, "audio_empty", "El audio llegó vacío. Grabalo de nuevo.")
        if len(data) > MAX_AUDIO_BYTES:
            return error(413, "audio_too_large", "El audio es demasiado largo. Grabá un reporte más corto.")
        try:
            # Blocking network call: run it off the event loop so other requests keep flowing.
            result = await run_in_threadpool(
                transcribe,
                data,
                filename=AUDIO_TYPES[mime],
                mime_type=mime,
                vocabulary=ingest.vocabulary_for(db, patient_id),
            )
        except TranscriptionError as exc:
            log.error("Web report %s: transcription failed: %s", message_id, exc)
            return error(502, "transcription_failed", exc.user_message)
        transcript = result.text
    elif transcript is None:
        transcript = text.strip()

    try:
        return await run_in_threadpool(
            ingest.process_report,
            patient_id=patient_id,
            caregiver_id=person_id,
            transcript=transcript,
            audio_ref=None,
            message_id=message_id,
        )
    except ingest.ProcessingUnavailable:
        log.error("Web report %s: process_report is not available yet", message_id)
        return error(
            503,
            "processing_unavailable",
            "No pudimos registrar el reporte: el análisis todavía no está disponible. Probá de nuevo más tarde.",
        )
