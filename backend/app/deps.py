"""Shared FastAPI dependencies: database session and the calling person."""

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.errors import api_error
from app.models import ROLE_PERMISSIONS, Patient, Permission, Report, Role, SessionLocal, role_for


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def current_person_id(request: Request) -> str:
    """Who is calling.

    SIMULATED until the login backend lands (CIA-26): the web app sends the
    person id in the `X-Person-Id` header. Anyone can claim any id, so the
    header is only honored when ALLOW_DEV_IDENTITY_HEADER=1 (local dev, demo
    with fictional data); otherwise every call is 401. Replace the body of this
    function with the session-cookie lookup; endpoints that depend on it do not change.
    """
    if os.environ.get("ALLOW_DEV_IDENTITY_HEADER") != "1":
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthenticated", "message": "El inicio de sesión todavía no está disponible."},
        )
    person_id = request.headers.get("X-Person-Id")
    if not person_id:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthenticated", "message": "Iniciá sesión para continuar."},
        )
    return person_id


@dataclass(frozen=True)
class PatientContext:
    person_id: str
    patient: Patient
    role: Role


def _authorize(db: Session, person_id: str, patient_id: str, permission: Permission) -> tuple[Patient, Role]:
    """404 when the patient is unknown or the caller has no access at all (no existence leak);
    403 when the caller's role lacks the permission."""
    patient = db.get(Patient, patient_id)
    role = role_for(db, person_id, patient_id) if patient is not None else None
    if patient is None or role is None:
        raise api_error(404, "not_found", "No encontramos a ese paciente.")
    if permission not in ROLE_PERMISSIONS[role]:
        raise api_error(403, "forbidden", "Tu rol no permite hacer esto con este paciente.")
    return patient, role


def patient_access(permission: Permission) -> Callable[..., PatientContext]:
    """Dependency factory: `ctx: PatientContext = Depends(patient_access(Permission.read_reports))`."""

    def dependency(
        patient_id: str,
        person_id: str = Depends(current_person_id),
        db: Session = Depends(get_db),
    ) -> PatientContext:
        patient, role = _authorize(db, person_id, patient_id, permission)
        return PatientContext(person_id=person_id, patient=patient, role=role)

    return dependency


def report_access(db: Session, person_id: str, report_id: str, permission: Permission) -> tuple[Report, Role]:
    """Same 404/403 rules as `patient_access`, for `/reports/{id}` routes."""
    report = db.get(Report, report_id)
    if report is None:
        raise api_error(404, "not_found", "No encontramos ese reporte.")
    try:
        _, role = _authorize(db, person_id, report.patient_id, permission)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise api_error(404, "not_found", "No encontramos ese reporte.") from None
        raise
    return report, role
