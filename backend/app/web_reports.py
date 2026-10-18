"""POST /patients/{patient_id}/reports: an end-of-shift report from the web app.

Accepts JSON `{client_id, text}` or multipart `client_id` + `audio`. Audio goes
through the transcription step; then both go through `ingest.process_report`.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import ingest, notify
from app.deps import current_person_id, get_db
from app.errors import error_response
from app.models import Patient, Permission, can, role_for
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


@router.post("/patients/{patient_id}/reports")
async def create_report(
    patient_id: str,
    request: Request,
    background: BackgroundTasks,
    person_id: str = Depends(current_person_id),
    db: Session = Depends(get_db),
):
    # No membership at all -> 404, like deps.patient_access: never confirm a patient exists.
    if db.get(Patient, patient_id) is None or role_for(db, person_id, patient_id) is None:
        return error_response(404, "not_found", "No encontramos a ese paciente.")
    if not can(db, person_id, patient_id, Permission.send_report):
        return error_response(403, "forbidden", "Tu rol no permite enviar reportes para este paciente.")

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        client_id, text, audio = form.get("client_id"), None, form.get("audio")
        if audio is None or isinstance(audio, str):
            return error_response(400, "audio_missing", "Falta el archivo de audio.")
    elif content_type.startswith("application/json"):
        try:
            body = json.loads(await request.body())
        except ValueError:
            return error_response(400, "invalid_json", "El cuerpo no es JSON válido.")
        if not isinstance(body, dict):
            return error_response(400, "invalid_json", "El cuerpo no es JSON válido.")
        client_id, text, audio = body.get("client_id"), body.get("text"), None
        if not isinstance(text, str) or not text.strip():
            return error_response(400, "text_missing", "El reporte está vacío. Escribí cómo estuvo el turno.")
    else:
        return error_response(415, "unsupported_media_type", "Enviá JSON con `text` o un formulario con `audio`.")

    if not isinstance(client_id, str) or not client_id.strip() or len(client_id) > MAX_CLIENT_ID:
        return error_response(400, "client_id_missing", "Falta `client_id` (o es demasiado largo).")
    message_id = ingest.web_message_id(person_id, client_id.strip())

    # A repeated client_id never transcribes again: process_report returns the stored result.
    existing = ingest.existing_report(db, message_id)
    if existing is not None and existing.patient_id != patient_id:
        return error_response(409, "client_id_conflict", "Ese identificador ya se usó para otro paciente. Generá uno nuevo.")
    transcript = existing.transcript if existing is not None else None
    segments: list[dict] = []
    voice_note: ingest.Audio | None = None
    # A retry of a stored report never transcribes again. It only attaches a voice note to a report
    # that came from audio (it has segments) and whose first upload failed: a typed report must never
    # gain a recording its transcript and quotes were not verified against.
    retry_needs_audio = existing is not None and existing.audio is None and bool(existing.segments)
    if audio is not None and (existing is None or retry_needs_audio):
        mime = (audio.content_type or "").split(";")[0].strip()
        if mime not in AUDIO_TYPES:
            return error_response(415, "unsupported_audio", "Formato de audio no soportado. Usá webm, ogg o m4a.")
        data = await audio.read()
        if not data:
            return error_response(400, "audio_empty", "El audio llegó vacío. Grabalo de nuevo.")
        if len(data) > MAX_AUDIO_BYTES:
            return error_response(413, "audio_too_large", "El audio es demasiado largo. Grabá un reporte más corto.")
        if transcript is None:
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
                return error_response(502, "transcription_failed", exc.user_message)
            transcript = result.text
            segments = result.segment_dicts()
            duration = result.duration
        else:
            duration = existing.segments[-1].get("end")  # end of the transcription's last segment
        voice_note = ingest.Audio(data, mime, duration)
    if transcript is None:
        transcript = text.strip()

    result = await run_in_threadpool(
        ingest.process_report,
        patient_id=patient_id,
        sender_id=person_id,
        transcript=transcript,
        audio_ref=None,
        message_id=message_id,
        segments=segments,
    )
    report_id = (result.get("report") or {}).get("id") if isinstance(result, dict) else None
    if isinstance(result, dict) and result.get("red_flag") and report_id:
        # Runs after the response is sent; dispatch is idempotent, so repeats are harmless.
        background.add_task(notify.dispatch_emergency, report_id)
    if voice_note is not None:
        # After the response: the caregiver never waits for storage, and a failure never loses the report.
        background.add_task(ingest.store_audio, result, voice_note)
    return result
