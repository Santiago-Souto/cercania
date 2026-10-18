"""process_report: transcript -> stored, verified report + alerts (CIA-7).

Single entry point behind ingest.process_report (docs/contract.md). Routing follows
AGENTS.md section 4.1. The model reads (triage, extraction); code decides everything
else: routing, comparison, alerts, confirmation text, what is stored.

Never raises to the caller for model or routing problems, never invents a result, and
never drops an emergency: a caregiver message flagged as an emergency is stored even
when extraction fails. Logs ids and counts only (transcripts are health data).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import compare, extract, models, serializers, triage as triage_mod
from .models import (
    Alert,
    AlertType,
    ChecklistItem,
    ItemSource,
    Report,
    ReportItem,
    ReportKind,
    ReportVersion,
    Role,
    VersionSource,
    active_care_plan,
    role_for,
)
from .segments import quote_times

log = logging.getLogger(__name__)

# Module-level so tests can point it at an in-memory database.
SessionLocal = models.SessionLocal

FORBIDDEN_MESSAGE = "Tu número no tiene acceso a este paciente, no se guardó nada."
NOT_A_REPORT_MESSAGE = (
    "Los reportes de turno los envían las personas cuidadoras. "
    "Podés ver el historial y las alertas en la aplicación web."
)
EMERGENCY_FALLBACK_REASON = "Posible emergencia indicada en el mensaje."
EXTRACTION_CRASH_MESSAGE = "No pudimos procesar el reporte. Volvé a intentar en un momento."

ITEM_ES = compare.ITEM_LABELS


# --- helpers -----------------------------------------------------------------------------


def _existing(session: Session, message_id: str) -> Report | None:
    return session.scalar(select(Report).where(Report.message_id == message_id))


def _result(session: Session, report: Report) -> dict:
    session.expire_all()  # read back from the database so first call and repeats match exactly
    return serializers.process_result(session, report)


def _run_models(transcript: str, role: Role, plan, triage_client, extract_client):
    """Triage always; extraction only for caregivers. Concurrent. Returns (triage, extraction|ExtractionError)."""

    def do_triage() -> triage_mod.Triage:
        return triage_mod.triage(transcript, sender_role=role, client=triage_client)

    def do_extract():
        try:
            return extract.extract(transcript, extract.plan_medications(plan), client=extract_client)
        except extract.ExtractionError as exc:
            return exc
        except Exception as exc:  # noqa: BLE001 - a model-side surprise must not crash the pipeline
            log.warning("extraction crashed: %s", type(exc).__name__)
            return extract.ExtractionError(EXTRACTION_CRASH_MESSAGE)

    if role != Role.caregiver:
        return do_triage(), None
    with ThreadPoolExecutor(max_workers=2) as pool:
        t_future = pool.submit(do_triage)
        e_future = pool.submit(do_extract)
        return t_future.result(), e_future.result()


def _history(session: Session, patient_id: str) -> tuple[list[list[dict]], list[str]]:
    """Items of the latest version of previous shift reports, newest first."""
    reports = session.scalars(
        select(Report)
        .where(Report.patient_id == patient_id, Report.kind == ReportKind.shift)
        .order_by(Report.created_at.desc())
        .limit(compare.CHANGE_WINDOW)
    ).all()
    items, ids = [], []
    for r in reports:
        if r.latest is None:
            continue
        items.append([serializers.serialize_item(i) for i in r.latest.items])
        ids.append(r.id)
    return items, ids


def confirmation_text(items: list[dict], alerts: list[dict], *, triage: triage_mod.Triage) -> str:
    """Spanish text sent back to the caregiver. Written by code from verified data, never by the model."""
    if triage.emergency:
        return triage_mod.EMERGENCY_REPLY
    # An unverified quote means code could not find the fact in the transcript: say so.
    recorded = [f"{ITEM_ES[i['item']]}: {i['value']}" + ("" if i.get("quote_verified") is not False else " (sin verificar)")
                for i in items if i["value"] is not None]
    parts = ["Registré: " + "; ".join(recorded) + "." if recorded else "No pude registrar ningún dato."]
    omissions = [a["detail"] for a in alerts if a["type"] == "omission"]
    if omissions:
        parts.append("Medicación: " + " ".join(omissions))
    changes = [a["detail"] for a in alerts if a["type"] == "change"]
    if changes:
        parts.append("Cambios: " + " ".join(changes))
    missing = [ITEM_ES[i["item"]] for i in items if i["value"] is None]
    if missing:
        parts.append("No mencionaste: " + ", ".join(missing) + ". Podés mandar otra nota.")
    else:
        parts.append("Podés mandar otra nota si querés agregar algo.")
    text = " ".join(parts)
    if triage.status.value == "failed":
        text += "\n\n" + triage_mod.TRIAGE_FAILED_LINE
    return text


def emergency_alert(triage: triage_mod.Triage, report_id: str) -> dict:
    return {
        "type": "emergency", "item": None, "detail": triage.reason or EMERGENCY_FALLBACK_REASON,
        "plan_ref": None, "evidence_quote": triage.quote, "evidence_verified": triage.quote_verified,
        "report_refs": [report_id],
    }


def add_alert(version: ReportVersion, data: dict, notifications: list | None = None) -> Alert:
    return Alert(
        report_version=version, type=AlertType(data["type"]),
        item=ChecklistItem(data["item"]) if data.get("item") else None,
        detail=data["detail"], plan_ref=data.get("plan_ref"),
        evidence_quote=data.get("evidence_quote"), evidence_verified=data.get("evidence_verified"),
        report_refs=list(data.get("report_refs") or []), notifications=list(notifications or []),
    )


# --- entry point -------------------------------------------------------------------------


def process_report(patient_id: str, sender_id: str, transcript: str, audio_ref: str | None,
                   message_id: str, segments: list[dict] | None = None, *,
                   triage_client=None, extract_client=None) -> dict:
    """Process one message. Returns a ProcessResult dict (docs/contract.md).

    status "ok": stored (or already stored: idempotent on message_id).
    status "needs_retry": caregiver report that could not be extracted; nothing stored.
    status "not_a_report": non-caregiver, no emergency; nothing stored.
    status "forbidden": sender has no access to the patient; nothing stored.

    audio_ref is accepted for the contract but not stored yet (channels pass None).
    segments ([{start, end, text}], [] for typed reports) are stored on the report and give
    each verified item quote its audio_start_sec / audio_end_sec (segments.quote_times).
    """
    session = SessionLocal()
    try:
        return _process(session, patient_id, sender_id, transcript, message_id, list(segments or []),
                        triage_client, extract_client)
    finally:
        session.close()


def _process(session: Session, patient_id: str, sender_id: str, transcript: str, message_id: str,
             segments: list[dict], triage_client, extract_client) -> dict:
    # 1. idempotency
    if (report := _existing(session, message_id)) is not None:
        log.info("duplicate message; returning report %s", report.id)
        return _result(session, report)

    # 2. who is sending (code)
    role = role_for(session, sender_id, patient_id)
    if role is None:
        return {"status": "forbidden", "message": FORBIDDEN_MESSAGE}

    # 3. models
    plan = active_care_plan(session, patient_id)
    triage, extraction = _run_models(transcript, role, plan, triage_client, extract_client)
    emergency = triage.emergency
    extracted = isinstance(extraction, extract.Extraction)

    # 4. routing
    if role == Role.caregiver:
        if not extracted and not emergency:
            message = extraction.message
            if triage.status.value == "failed":
                message += "\n\n" + triage_mod.TRIAGE_FAILED_LINE
            return {"status": "needs_retry", "message": message, "red_flag": False,
                    "triage": triage.as_contract()}
        kind = ReportKind.shift
    else:
        if not emergency:
            message = NOT_A_REPORT_MESSAGE
            if triage.status.value == "failed":
                message += "\n\n" + triage_mod.TRIAGE_FAILED_LINE
            return {"status": "not_a_report", "message": message, "red_flag": False,
                    "triage": triage.as_contract()}
        kind = ReportKind.emergency
        extraction = None

    # 5-7. build and store
    report_id = models.new_id("rep")
    report = Report(
        id=report_id, patient_id=patient_id, sender_id=sender_id, kind=kind, message_id=message_id,
        channel="web" if message_id.startswith("web:") else "whatsapp",
        transcript=transcript, segments=segments, red_flag=emergency,
        triage_status=triage.status, triage_reason=triage.reason, triage_quote=triage.quote,
        triage_quote_verified=triage.quote_verified, triage_model=triage.model,
    )
    version = ReportVersion(
        report=report, version=1, source=VersionSource.original, created_by=sender_id,
        extraction_raw=extraction.raw if extracted else None,
        model=extraction.model if extracted else None,
    )
    items: list[dict] = []
    alerts: list[dict] = []
    if emergency:
        alerts.append(emergency_alert(triage, report_id))
    if extracted:
        items = extraction.items
        history, history_ids = _history(session, patient_id)
        alerts += compare.compare(items, plan, history, report_id=report_id,
                                  history_report_ids=history_ids)
        for i in items:
            start, end = quote_times(i["quote"], segments) if i["quote_verified"] else (None, None)
            ReportItem(
                report_version=version, item=ChecklistItem(i["item"]), value=i["value"],
                level=i["level"], details=i["details"], quote=i["quote"],
                quote_verified=i["quote_verified"], audio_start_sec=start, audio_end_sec=end,
                source=ItemSource.transcript,
            )
    version.confirmation_text = confirmation_text(items, alerts, triage=triage)

    try:
        session.add(report)
        session.flush()  # assigns report.id; unique message_id is enforced here
        for a in alerts:
            session.add(add_alert(version, a))
        session.commit()
    except IntegrityError:
        # Concurrent delivery of the same message won the race.
        session.rollback()
        if (existing := _existing(session, message_id)) is not None:
            return _result(session, existing)
        raise

    log.info("report %s stored kind=%s red_flag=%s items=%d alerts=%d triage=%s",
             report.id, kind.value, emergency, sum(1 for i in items if i["value"] is not None),
             len(alerts), triage.status.value)
    return _result(session, report)
