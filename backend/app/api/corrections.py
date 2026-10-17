"""Corrections route.

POST /reports/{id}/corrections (correct_report): adds a new report_version authored by the caller.
Earlier versions are never touched (evidence trail, AGENTS.md section 5).
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import compare, models, process, schemas, serializers, triage as triage_mod
from app.deps import current_person_id, get_db, report_access
from app.errors import api_error
from app.models import (
    AlertType,
    ChecklistItem,
    ItemSource,
    Permission,
    ReportItem,
    ReportKind,
    ReportVersion,
    VersionSource,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["corrections"])


@router.post("/reports/{report_id}/corrections", response_model=schemas.Report)
def correct_report(
    report_id: str,
    body: schemas.CorrectionsRequest,
    person_id: str = Depends(current_person_id),
    db: Session = Depends(get_db),
) -> dict:
    report, _ = report_access(db, person_id, report_id, Permission.correct_report)
    if report.kind == ReportKind.emergency or report.latest is None:
        raise api_error(409, "not_correctable",
                        "Este reporte es una emergencia y no tiene datos para corregir.")
    previous = report.latest

    # Last correction per item wins. An empty value means "not mentioned".
    corrected: dict[str, str | None] = {}
    for c in body.corrections:
        corrected[c.item] = (c.value or "").strip() or None

    version = ReportVersion(
        report_id=report.id, version=models.next_version(db, report.id), source=VersionSource.correction,
        created_by=person_id,
    )
    items: list[dict] = []
    for old in previous.items:
        if old.item.value in corrected:
            row = ReportItem(report_version=version, item=old.item, value=corrected[old.item.value],
                             level=None, details=None, quote=None, quote_verified=None,
                             source=ItemSource.correction)
        else:
            row = ReportItem(
                report_version=version, item=old.item, value=old.value, level=old.level,
                details=old.details, quote=old.quote, quote_verified=old.quote_verified,
                audio_start_sec=old.audio_start_sec, audio_end_sec=old.audio_end_sec, source=old.source)
        items.append(serializers.serialize_item(row))

    plan = models.active_care_plan(db, report.patient_id)
    alerts = compare.compare(items, plan, [], report_id=report.id, include_changes=False)
    version.confirmation_text = process.confirmation_text(
        items, alerts, triage=triage_mod.Triage(status=models.TriageStatus.ok, emergency=False))

    # Carry over what this correction does not recompute: the emergency (with its notification
    # log) and change alerts of items that were not corrected.
    carried = []
    for a in previous.alerts:
        if a.type == AlertType.emergency or (
                a.type == AlertType.change and a.item is not None and a.item.value not in corrected):
            carried.append(a)

    try:
        db.add(version)
        db.flush()
        for a in alerts:
            db.add(process.add_alert(version, a))
        for a in carried:
            db.add(process.add_alert(
                version, {"type": a.type.value, "item": a.item.value if a.item else None,
                          "detail": a.detail, "plan_ref": a.plan_ref, "evidence_quote": a.evidence_quote,
                          "evidence_verified": a.evidence_verified, "report_refs": a.report_refs},
                notifications=a.notifications))
        db.commit()
    except IntegrityError:
        db.rollback()  # two corrections raced for the same version number
        raise api_error(409, "version_conflict", "Otra corrección se guardó al mismo tiempo. Volvé a intentar.")

    log.info("report %s corrected: version=%d items=%d by=%s", report.id, version.version,
             len(corrected), person_id)
    db.expire_all()
    return serializers.serialize_report(db, db.get(models.Report, report.id))
