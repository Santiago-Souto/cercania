"""Report read routes: GET /reports/{id} (latest version), /reports/{id}/versions (oldest first)
and /reports/{id}/audio (signed URL for the original voice note).

All need read_reports on the report's patient.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas, storage
from app.deps import current_person_id, get_db, report_access
from app.errors import api_error
from app.models import Permission
from app.serializers import serialize_report, serialize_version

log = logging.getLogger(__name__)
router = APIRouter(tags=["reports"])


@router.get("/reports/{report_id}", response_model=schemas.Report)
def get_report(
    report_id: str,
    person_id: str = Depends(current_person_id),
    db: Session = Depends(get_db),
) -> dict:
    report, _ = report_access(db, person_id, report_id, Permission.read_reports)
    return serialize_report(db, report)


@router.get("/reports/{report_id}/versions", response_model=schemas.ReportVersions)
def get_report_versions(
    report_id: str,
    person_id: str = Depends(current_person_id),
    db: Session = Depends(get_db),
) -> dict:
    report, _ = report_access(db, person_id, report_id, Permission.read_reports)
    return {
        "report_id": report.id,
        "versions": [serialize_version(db, v) for v in sorted(report.versions, key=lambda v: v.version)],
    }


@router.get("/reports/{report_id}/audio", response_model=schemas.ReportAudio)
def get_report_audio(
    report_id: str,
    person_id: str = Depends(current_person_id),
    db: Session = Depends(get_db),
) -> dict:
    """JSON, not a redirect: the web calls it with its identity header, then plays `url`."""
    report, _ = report_access(db, person_id, report_id, Permission.read_reports)
    audio = report.audio
    if audio is None:
        raise api_error(404, "not_found", "Este reporte no tiene audio guardado.")
    try:
        url = storage.signed_url(audio.storage_path)
    except storage.StorageError as exc:
        log.error("Signed URL for report %s failed: %s", report.id, exc)
        raise api_error(502, "audio_unavailable", "No pudimos cargar el audio. Probá de nuevo en un momento.") from None
    return {"url": url, "expires_in_sec": storage.SIGNED_URL_TTL_SEC}
