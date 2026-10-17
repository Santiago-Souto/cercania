"""Hand-off from any input channel (web app, WhatsApp) to the brain.

Every channel ends here after it has a transcript, so there is a single path
into `process_report` (docs/contract.md).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Patient, Report, active_care_plan

# Where Dev A's process_report is expected to live (CIA-7).
PROCESS_REPORT_MODULE = "app.process"


class ProcessingUnavailable(Exception):
    """process_report is not merged yet. Never replaced by a fake result."""


def vocabulary_for(session: Session, patient_id: str) -> list[str]:
    """Transcription hint: the patient's own words plus their medication names."""
    patient = session.get(Patient, patient_id)
    words = list(patient.vocabulary or []) if patient else []
    plan = active_care_plan(session, patient_id)
    if plan:
        words += [m.name for m in plan.medications]
    return words


def existing_transcript(session: Session, message_id: str) -> str | None:
    """Transcript of a report already stored under this message id, if any."""
    return session.scalar(select(Report.transcript).where(Report.message_id == message_id))


def process_report(patient_id: str, caregiver_id: str, transcript: str, audio_ref: str | None, message_id: str) -> dict:
    try:
        module = __import__(PROCESS_REPORT_MODULE, fromlist=["process_report"])
        brain = module.process_report
    except (ImportError, AttributeError) as exc:
        raise ProcessingUnavailable(str(exc)) from exc
    return brain(
        patient_id=patient_id,
        caregiver_id=caregiver_id,
        transcript=transcript,
        audio_ref=audio_ref,
        message_id=message_id,
    )
