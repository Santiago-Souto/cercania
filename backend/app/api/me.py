"""Current-person routes: GET /me (person + memberships) and GET /me/patients (MyPatient list)."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import schemas
from app.deps import current_person_id, get_db
from app.errors import api_error
from app.models import AlertType, Patient, PatientAccess, Person, Report, ReportVersion, Role

router = APIRouter(tags=["me"])

_OPEN_ALERT_TYPES = {AlertType.emergency, AlertType.omission, AlertType.change}


def _memberships(db: Session, person_id: str) -> list[tuple[PatientAccess, Patient]]:
    rows = db.execute(
        select(PatientAccess, Patient)
        .join(Patient, PatientAccess.patient_id == Patient.id)
        .where(PatientAccess.person_id == person_id)
        .order_by(Patient.display_name, Patient.id)
    )
    return [(a, p) for a, p in rows]


@router.get("/me", response_model=schemas.Me)
def get_me(person_id: str = Depends(current_person_id), db: Session = Depends(get_db)) -> dict:
    person = db.get(Person, person_id)
    if person is None:
        raise api_error(401, "unauthenticated", "Iniciá sesión para continuar.")
    return {
        "id": person.id,
        "display_name": person.display_name,
        "phone_last4": person.phone[-4:],
        "memberships": [
            {"patient_id": p.id, "display_name": p.display_name, "role": a.role.value}
            for a, p in _memberships(db, person.id)
        ],
    }


@router.get("/me/patients", response_model=schemas.MyPatients)
def get_my_patients(person_id: str = Depends(current_person_id), db: Session = Depends(get_db)) -> dict:
    """One entry per membership, with report-derived status for the dashboard.

    - `last_report_at`: created_at of the patient's newest report, else null.
    - `red_flag`: some report from the last 24 h has red_flag.
    - `open_alerts`: emergency/omission/change alerts on the latest version of reports from the
      last 24 h (missing_item alerts are not counted so the number stays meaningful).
    - `missing_report`: no report in the last 24 h.
    - Role `patient` never sees reports or alerts (AGENTS.md section 6): all four are null.
    """
    if db.get(Person, person_id) is None:
        raise api_error(401, "unauthenticated", "Iniciá sesión para continuar.")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    out = []
    for access, patient in _memberships(db, person_id):
        entry = {"id": patient.id, "display_name": patient.display_name, "location": None,
                 "role": access.role.value, "last_report_at": None, "open_alerts": None,
                 "red_flag": None, "missing_report": None}
        if access.role != Role.patient:
            entry["last_report_at"] = db.scalar(
                select(func.max(Report.created_at)).where(Report.patient_id == patient.id))
            recent = list(db.scalars(
                select(Report)
                .where(Report.patient_id == patient.id, Report.created_at >= cutoff)
                .options(selectinload(Report.versions).selectinload(ReportVersion.alerts))
            ))
            entry["red_flag"] = any(r.red_flag for r in recent)
            entry["missing_report"] = not recent
            entry["open_alerts"] = sum(
                1 for r in recent if r.latest
                for a in r.latest.alerts if a.type in _OPEN_ALERT_TYPES
            )
        out.append(entry)
    return {"patients": out}
