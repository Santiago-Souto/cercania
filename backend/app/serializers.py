"""ORM -> plain dicts matching schemas.py (docs/contract.md). Pure functions, no DB writes."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    Alert,
    Notification,
    Patient,
    Person,
    Report,
    ReportItem,
    ReportKind,
    ReportVersion,
    Role,
    active_care_plan,
    role_for,
)


def person_ref(person: Person, role: Role | None) -> dict:
    return {"id": person.id, "display_name": person.display_name,
            "role": role.value if role else None}


def serialize_item(item: ReportItem) -> dict:
    return {
        "item": item.item.value,
        "value": item.value,
        "level": item.level,
        "details": item.details,
        "quote": item.quote,
        "quote_verified": item.quote_verified,
        "audio_start_sec": item.audio_start_sec,
        "audio_end_sec": item.audio_end_sec,
        "source": item.source.value if item.source else None,
    }


def serialize_alert(alert: Alert, report: Report | None = None,
                    version: ReportVersion | None = None) -> dict:
    if version is None:
        version = alert.report_version
    if report is None and version is not None:
        report = version.report
    return {
        "id": alert.id,
        "type": alert.type.value,
        "item": alert.item.value if alert.item else None,
        "detail": alert.detail,
        "plan_ref": alert.plan_ref,
        "evidence_quote": alert.evidence_quote,
        "evidence_verified": alert.evidence_verified,
        "report_refs": list(alert.report_refs or []),
        "notifications": [
            {"to": n.get("to"), "person_id": n.get("person_id"), "channel": n.get("channel"),
             "status": n.get("status"), "error": n.get("error")}
            for n in (alert.notifications or [])
        ],
        "report_id": report.id if report else None,
        "report_version": version.version if version else None,
        "created_at": alert.created_at,
    }


def serialize_triage(report: Report) -> dict | None:
    """None for seed fixtures, which never went through triage."""
    if report.triage_status is None:
        return None
    return {
        "status": report.triage_status.value,
        "emergency": report.red_flag,
        "reason": report.triage_reason,
        "quote": report.triage_quote,
        "quote_verified": report.triage_quote_verified,
    }


def _sender_ref(session: Session, report: Report) -> dict:
    return person_ref(report.sender, role_for(session, report.sender_id, report.patient_id))


def serialize_report(session: Session, report: Report, version: ReportVersion | None = None) -> dict:
    version = version or report.latest
    sender = _sender_ref(session, report)
    audio = report.audio
    emergency_kind = report.kind == ReportKind.emergency
    return {
        "id": report.id,
        "version": version.version if version else 0,
        "created_at": report.created_at,
        "kind": report.kind.value,
        "channel": report.channel,
        "sender": sender,
        "caregiver": dict(sender),
        "transcript": report.transcript,
        # SIMULATED until object storage lands: placeholder path, not a playable URL yet.
        "audio_url": f"/media/{report.id}" if audio else None,
        "audio_duration_sec": audio.duration_sec if audio else None,
        "items": [serialize_item(i) for i in version.items] if version else [],
        "missing_items": [] if emergency_kind or not version else version.missing_items,
        "alerts": [serialize_alert(a, report, version) for a in version.alerts] if version else [],
        "red_flag": report.red_flag,
        "red_flag_quote": report.triage_quote,
        "triage": serialize_triage(report),
        "confirmation_text": version.confirmation_text if version else None,
    }


def serialize_version(session: Session, version: ReportVersion) -> dict:
    report = version.report
    creator = session.get(Person, version.created_by)
    created_by = (person_ref(creator, role_for(session, creator.id, report.patient_id))
                  if creator else {"id": version.created_by, "display_name": "", "role": None})
    return {
        "version": version.version,
        "source": version.source.value,
        "created_at": version.created_at,
        "created_by": created_by,
        "items": [serialize_item(i) for i in version.items],
        "missing_items": [] if report.kind == ReportKind.emergency else version.missing_items,
        "alerts": [serialize_alert(a, report, version) for a in version.alerts],
        "confirmation_text": version.confirmation_text,
    }


def serialize_patient(session: Session, patient: Patient) -> dict:
    plan = active_care_plan(session, patient.id)
    care_plan = None
    if plan is not None:
        care_plan = {
            "medications": [{"id": m.id, "name": m.name, "dose": m.dose_text, "times": list(m.times or [])}
                            for m in plan.medications],
            "indications": list(plan.indications or []),
            "allergies": list(plan.allergies or []),
        }
    return {"id": patient.id, "display_name": patient.display_name, "location": patient.location,
            "care_plan": care_plan}


def serialize_notification(n: Notification, patient_display_name: str) -> dict:
    return {
        "id": n.id,
        "patient_id": n.patient_id,
        "patient_display_name": patient_display_name,
        "alert_id": n.alert_id,
        "report_id": n.report_id,
        "recipient": n.recipient,
        "channel": n.channel.value,
        "status": n.status.value,
        "title": n.title,
        "body": n.body,
        "created_at": n.created_at,
        "read_at": n.read_at,
    }


def process_result(session: Session, report: Report) -> dict:
    """ProcessResult (docs/contract.md) rebuilt from a stored report, for idempotent repeats."""
    full = serialize_report(session, report)
    return {
        "status": "ok",
        "report": {"id": full["id"], "version": full["version"]},
        "items": full["items"],
        "missing_items": full["missing_items"],
        "alerts": full["alerts"],
        "red_flag": full["red_flag"],
        "triage": full["triage"],
        "confirmation_text": full["confirmation_text"],
    }
