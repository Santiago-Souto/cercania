"""Hand-off from any input channel (today only the web app) to the brain.

Every channel ends here after it has a transcript, so there is a single path
into `process_report` (docs/contract.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, process, storage
from app.models import File, FileKind, Patient, Report, active_care_plan

log = logging.getLogger(__name__)

def vocabulary_for(session: Session, patient_id: str) -> list[str]:
    """Transcription hint: the patient's own words plus their medication names."""
    patient = session.get(Patient, patient_id)
    words = list(patient.vocabulary or []) if patient else []
    plan = active_care_plan(session, patient_id)
    if plan:
        words += [m.name for m in plan.medications]
    return words


def web_message_id(person_id: str, client_id: str) -> str:
    """Web client ids are chosen by the browser; namespacing by person keeps one
    user's id from ever matching another user's report."""
    return f"web:{person_id}:{client_id}"


def existing_report(session: Session, message_id: str) -> Report | None:
    return session.scalar(select(Report).where(Report.message_id == message_id))


def process_report(patient_id: str, sender_id: str, transcript: str, audio_ref: str | None, message_id: str,
                   segments: list[dict] | None = None) -> dict:
    """`segments`: timestamped transcript pieces from transcription; [] for typed reports."""
    return process.process_report(
        patient_id=patient_id,
        sender_id=sender_id,
        transcript=transcript,
        audio_ref=audio_ref,
        message_id=message_id,
        segments=segments or [],
    )


@dataclass
class Audio:
    """The original voice note, kept until the report is stored (CIA-44)."""

    data: bytes
    mime_type: str
    duration_sec: float | None = None


def store_audio(result: dict, audio: Audio | None, *, session_factory=None) -> bool:
    """After process_report: keep the voice note of a stored report in object storage.

    Only for status "ok" with a report id. Idempotent (one object path and one `file`
    row per report). Never raises: the report and the reply never depend on storage.
    Logs ids only.
    """
    report_id = (result.get("report") or {}).get("id") if isinstance(result, dict) else None
    if not report_id or result.get("status") != "ok" or audio is None or not audio.data:
        return False
    if not storage.configured():
        return False
    factory = session_factory or models.SessionLocal
    try:
        with factory() as session:
            report = session.get(Report, report_id)
            if report is None or report.audio is not None:
                return False
            path = storage.audio_path(report.patient_id, report.id, audio.mime_type)
            storage.upload(path, audio.data, audio.mime_type)
            session.add(File(
                patient_id=report.patient_id, uploaded_by=report.sender_id, report_id=report.id,
                kind=FileKind.audio, storage_path=path, mime_type=audio.mime_type,
                size_bytes=len(audio.data), duration_sec=audio.duration_sec,
            ))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()  # a concurrent delivery of the same message stored it first
                return False
    except Exception as exc:  # noqa: BLE001 - storage must never break the reply path
        log.error("Audio for report %s not stored: %s", report_id, exc)
        return False
    log.info("Audio for report %s stored (%d bytes)", report_id, len(audio.data))
    return True
