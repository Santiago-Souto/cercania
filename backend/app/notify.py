"""Emergency notifications (AGENTS.md 4.2, step 3).

Who is notified comes from `models.emergency_recipients` (code, never the model).
Primary channel: the in-app inbox (`notification` rows with channel `web`, polled by
the web). WhatsApp is best-effort behind NOTIFY_WHATSAPP=1: every attempt is recorded
as sent/failed/skipped, on the `notification` table and in `alert.notifications`
so a failure is visible on the alert, never silent.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import whatsapp
from app.query import _local_tz
from app.models import (
    Alert,
    AlertType,
    Notification,
    NotificationChannel,
    NotificationStatus,
    Patient,
    Person,
    Report,
    ReportVersion,
    SessionLocal,
    emergency_recipients,
)

log = logging.getLogger(__name__)

WHATSAPP_DISABLED = "WhatsApp desactivado (NOTIFY_WHATSAPP=0)"


def whatsapp_enabled() -> bool:
    return os.environ.get("NOTIFY_WHATSAPP") == "1"


def _summary(n: Notification) -> dict:
    return {"to": n.recipient, "person_id": n.person_id, "channel": n.channel.value,
            "status": n.status.value, "error": n.error}


def _local_time(report: Report) -> str:
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


def _send_whatsapp(sender, phone: str, text: str) -> tuple[NotificationStatus, str | None]:
    to = re.sub(r"\D", "", phone or "")
    if not to:
        return NotificationStatus.failed, "Sin número de teléfono registrado."
    try:
        res = sender.send_text_result(to, text)
        template = os.environ.get("WHATSAPP_EMERGENCY_TEMPLATE")
        if not res.ok and res.error_code == whatsapp.OUTSIDE_WINDOW and template:
            res = sender.send_template(to, template, os.environ.get("WHATSAPP_TEMPLATE_LANG", "es"))
    except Exception as exc:  # noqa: BLE001 - a failed send must be recorded, not raised
        log.exception("WhatsApp notification crashed")
        return NotificationStatus.failed, f"Error inesperado: {exc.__class__.__name__}"
    if res.ok:
        return NotificationStatus.sent, None
    detail = res.error or "Error desconocido"
    if res.error_code == whatsapp.OUTSIDE_WINDOW:
        detail += " (fuera de la ventana de 24 h; requiere plantilla aprobada)"
    return NotificationStatus.failed, f"[{res.error_code}] {detail}" if res.error_code else detail


def dispatch_emergency(report_id: str, *, session_factory=SessionLocal, whatsapp_sender=None) -> list[dict]:
    """Notify everyone who must know about an emergency report. Never raises.

    Idempotent per recipient and channel: rows that already exist are never sent again.
    `whatsapp_sender` needs `send_text_result(to, text)` and `send_template(to, name, lang)`;
    defaults to the `whatsapp` module.
    """
    try:
        return _dispatch(report_id, session_factory, whatsapp_sender or whatsapp)
    except Exception:  # noqa: BLE001
        log.exception("Emergency notification dispatch failed for report %s", report_id)
        return []


def _dispatch(report_id: str, session_factory, sender) -> list[dict]:
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
        # Idempotent per (recipient, channel): a dispatch that died between the web
        # commit and the WhatsApp commit still sends the missing WhatsApp rows on retry.
        done = {(n.recipient, n.person_id, n.channel) for n in rows}
        recipients = emergency_recipients(session, report.patient_id, report.sender_id)
        todo_web = [r for r in recipients if r["person_id"]
                    and (r["to"], r["person_id"], NotificationChannel.web) not in done]
        todo_whatsapp = [r for r in recipients
                         if (r["to"], r["person_id"], NotificationChannel.whatsapp) not in done]
        if not todo_web and not todo_whatsapp:
            return [_summary(n) for n in rows]

        patient = session.get(Patient, report.patient_id)
        title, body = build_message(session, report, patient, alert)

        def row(r: dict, channel: NotificationChannel, status: NotificationStatus,
                error: str | None) -> Notification:
            n = Notification(alert_id=alert.id, report_id=report_id, patient_id=report.patient_id,
                             person_id=r["person_id"], recipient=r["to"], channel=channel,
                             status=status, error=error, title=title, body=body)
            session.add(n)
            return n

        rows += [row(r, NotificationChannel.web, NotificationStatus.sent, None) for r in todo_web]
        alert.notifications = [_summary(n) for n in rows]
        session.commit()  # the web inbox is complete before any slow Meta call

        enabled = whatsapp_enabled()
        for r in todo_whatsapp:
            if enabled:
                status, error = _send_whatsapp(sender, r["phone"], f"{title}\n{body}")
            else:
                status, error = NotificationStatus.skipped, WHATSAPP_DISABLED
            rows.append(row(r, NotificationChannel.whatsapp, status, error))
            if status is NotificationStatus.failed:
                log.error("Emergency WhatsApp to %s failed: %s", r["to"], error)
        summaries = [_summary(n) for n in rows]
        alert.notifications = summaries
        session.commit()
        return summaries
