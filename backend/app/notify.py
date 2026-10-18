"""Emergency notifications (AGENTS.md 4.2, step 3) and patient help / red-flag messages (AGENTS.md 7).

Who is notified comes from `models.emergency_recipients` (code, never the model).
The only channel is the in-app inbox (`notification` rows with channel `web`, polled by
the web). Every notification is recorded on the `notification` table and in
`alert.notifications`, so the alert shows who was notified.
"""

from __future__ import annotations

import logging
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.query import _local_tz
from app.models import (
    Alert,
    AlertType,
    Notification,
    NotificationChannel,
    NotificationStatus,
    Patient,
    PatientMessage,
    PatientMessageKind,
    Person,
    Report,
    ReportVersion,
    SessionLocal,
    emergency_recipients,
    patient_team,
)

log = logging.getLogger(__name__)

def _summary(n: Notification) -> dict:
    return {"to": n.recipient, "person_id": n.person_id, "channel": n.channel,
            "status": n.status.value, "error": n.error}


def _local_time(report: Report | PatientMessage) -> str:
    created = report.created_at
    if created.tzinfo is None:  # SQLite returns naive UTC
        created = created.replace(tzinfo=timezone.utc)
    # Servers run in UTC; the reader is in APP_TIMEZONE.
    return created.astimezone(_local_tz()).strftime("%H:%M")


def build_message(session: Session, report: Report, patient: Patient, alert: Alert) -> tuple[str, str]:
    """Title and body. No transcript, no clinical advice."""
    sender = session.get(Person, report.sender_id)
    who = sender.display_name if sender else "Una persona"
    title = f"Emergencia: {patient.display_name}"
    parts = [f"{who} reportó una emergencia a las {_local_time(report)}."]
    reason = (report.triage_reason or "").strip().rstrip(".")
    if reason:
        parts.append(f"Motivo: {reason}.")
    parts.append("Abrí CercanIA para ver el reporte.")
    return title, " ".join(parts)


def _emergency_alert(session: Session, report_id: str) -> Alert | None:
    return session.scalars(
        select(Alert)
        .join(ReportVersion, ReportVersion.id == Alert.report_version_id)
        .where(ReportVersion.report_id == report_id, Alert.type == AlertType.emergency)
        .order_by(ReportVersion.version.desc(), Alert.id.desc())
    ).first()


def dispatch_emergency(report_id: str, *, session_factory=SessionLocal) -> list[dict]:
    """Notify everyone who must know about an emergency report. Never raises.

    Idempotent per recipient: people who already have a notification row are not notified again.
    """
    try:
        return _dispatch(report_id, session_factory)
    except Exception:  # noqa: BLE001
        log.exception("Emergency notification dispatch failed for report %s", report_id)
        return []


def _dispatch(report_id: str, session_factory) -> list[dict]:
    with session_factory() as session:
        report = session.get(Report, report_id)
        if report is None:
            log.error("Emergency dispatch: report %s not found", report_id)
            return []
        alert = _emergency_alert(session, report_id)
        if alert is None:
            return []
        rows = list(session.scalars(
            select(Notification).where(Notification.alert_id == alert.id)
            .order_by(Notification.created_at, Notification.id)
        ).all())
        done = {(n.recipient, n.person_id) for n in rows}
        recipients = emergency_recipients(session, report.patient_id, report.sender_id)
        todo = [r for r in recipients if (r["to"], r["person_id"]) not in done]
        if not todo:
            return [_summary(n) for n in rows]

        patient = session.get(Patient, report.patient_id)
        title, body = build_message(session, report, patient, alert)
        for r in todo:
            n = Notification(alert_id=alert.id, report_id=report_id, patient_id=report.patient_id,
                             person_id=r["person_id"], recipient=r["to"], channel=NotificationChannel.web.value,
                             status=NotificationStatus.sent, error=None, title=title, body=body)
            session.add(n)
            rows.append(n)
        summaries = [_summary(n) for n in rows]
        alert.notifications = summaries
        session.commit()
        return summaries


# --- patient messages (AGENTS.md 7) ----------------------------------------------------------


def patient_message_text(patient: Patient, message: PatientMessage) -> tuple[str, str]:
    """Title and body written by code. Never the patient's words, never clinical advice."""
    at = _local_time(message)
    if message.kind is PatientMessageKind.help:
        return (f"Pedido de ayuda: {patient.display_name}",
                f"{patient.display_name} pidió ayuda a las {at}. Abrí CercanIA.")
    parts = [f"{patient.display_name} envió un mensaje a las {at} que puede ser una emergencia."]
    reason = (message.triage_reason or "").strip().rstrip(".")
    if reason:
        parts.append(f"Motivo: {reason}.")
    parts.append("Abrí CercanIA.")
    return f"Posible emergencia: {patient.display_name}", " ".join(parts)


def notify_patient_team(session: Session, message: PatientMessage) -> list[str]:
    """Web inbox rows for every caregiver and health-team member; returns their person ids.

    Committed by the caller together with the message, so the response's `notified` is true.
    """
    patient = session.get(Patient, message.patient_id)
    title, body = patient_message_text(patient, message)
    recipients = patient_team(session, message.patient_id, message.sender_id)
    for r in recipients:
        session.add(Notification(patient_message_id=message.id, patient_id=message.patient_id,
                                 person_id=r["person_id"], recipient=r["to"], channel=NotificationChannel.web.value,
                                 status=NotificationStatus.sent, title=title, body=body))
    return [r["person_id"] for r in recipients]
