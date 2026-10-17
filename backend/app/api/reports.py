"""Report read routes: GET /reports/{id} (latest version) and /reports/{id}/versions (oldest first).

Both need read_reports on the report's patient.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas
from app.deps import current_person_id, get_db, report_access
from app.models import Permission
from app.serializers import serialize_report, serialize_version

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
