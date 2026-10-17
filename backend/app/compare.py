"""Plan / history / checklist comparison. Pure code: no model, no database.

Produces alert dicts (type, item, detail, plan_ref, evidence_quote, evidence_verified,
report_refs) for `missing_item`, `omission` and `change`. The `emergency` alert comes
from triage, not from here.

Contract rule: a value whose quote is not verified is never used to raise an
omission or change alert; it is treated as unclear (docs/contract.md).
"""

from __future__ import annotations

from collections import Counter

from .models import CarePlan

# Spanish names for messages shown to the caregiver.
ITEM_LABELS = {
    "appetite": "apetito",
    "sleep": "sueño",
    "urination": "diuresis",
    "medication": "medicación",
    "mood": "ánimo",
    "mobility": "movilidad",
    "pain": "dolor",
    "incidents": "incidentes",
}
LEVEL_LABELS = {
    "appetite": {"low": "bajo", "none": "sin apetito"},
    "sleep": {"poor": "sueño malo"},
    "urination": {"low": "baja", "none": "sin diuresis"},
    "mood": {"low": "decaído", "agitated": "agitado", "confused": "confuso"},
    "mobility": {"reduced": "reducida", "none": "sin movilidad"},
    "pain": {"present": "con dolor"},
    "incidents": {"present": "con incidentes"},
}
# The level that counts as "usual"; any other level is worth comparing.
NORMAL_LEVEL = {"pain": "none", "incidents": "none"}  # every other item: "normal"

CHANGE_WINDOW = 3  # previous shift reports looked at


def is_normal(item: str, level: str) -> bool:
    return level == NORMAL_LEVEL.get(item, "normal")


def _alert(type_: str, item: str | None, detail: str, report_refs: list[str], *,
           plan_ref: str | None = None, quote: str | None = None,
           verified: bool | None = None) -> dict:
    return {"type": type_, "item": item, "detail": detail, "plan_ref": plan_ref,
            "evidence_quote": quote, "evidence_verified": verified, "report_refs": report_refs}


# --- missing_item ----------------------------------------------------------------------


def missing_alerts(items: list[dict], report_id: str | None) -> list[dict]:
    refs = [report_id] if report_id else []
    return [
        _alert("missing_item", i["item"], f"No se mencionó: {ITEM_LABELS[i['item']]}.", list(refs))
        for i in items if i["value"] is None
    ]


# --- omission (care plan vs report) ------------------------------------------------------


def omission_alerts(items: list[dict], plan: CarePlan | None, report_id: str | None) -> list[dict]:
    """One alert per scheduled dose that is not confirmed as given."""
    if plan is None:
        return []
    refs = [report_id] if report_id else []
    med = next((i for i in items if i["item"] == "medication"), None)
    if med is not None and med["value"] is not None and med.get("details") is None:
        return []  # typed correction without per-dose detail: nothing to compare
    item_verified = med is None or med.get("quote_verified") is not False
    doses = ((med or {}).get("details") or {}).get("doses") or []
    by_slot = {(d.get("plan_ref"), d.get("time")): d for d in doses}

    alerts = []
    for m in plan.medications:
        for t in m.times:
            label = f"{m.name} {t}"
            dose = by_slot.get((m.id, t))
            if dose is None:
                alerts.append(_alert("omission", "medication", f"{label}: no se mencionó.", list(refs),
                                     plan_ref=m.id))
                continue
            given = dose.get("given")
            verified = item_verified and dose.get("quote_verified") is True
            if given is True and verified:
                continue
            if given is False and verified:
                alerts.append(_alert("omission", "medication", f"{label}: no se dio.", list(refs),
                                     plan_ref=m.id, quote=dose.get("quote"), verified=True))
            else:
                # unclear answer, or a value whose quote could not be verified: never asserted
                alerts.append(_alert("omission", "medication", f"{label}: no está claro.", list(refs),
                                     plan_ref=m.id))
    return alerts


# --- change (this report vs previous shifts) ---------------------------------------------


def _levels(history: list[list[dict]], item: str) -> list[str | None]:
    """Level of `item` in each previous report, newest first (None = not mentioned)."""
    out = []
    for items in history[:CHANGE_WINDOW]:
        row = next((i for i in items if i["item"] == item), None)
        out.append(row["level"] if row and row["value"] is not None else None)
    return out


def change_alerts(items: list[dict], history: list[list[dict]], report_id: str | None,
                  history_report_ids: list[str]) -> list[dict]:
    """Conservative: needs a verified non-normal level now and a clear baseline.

    1. differs from the most common level of the last 3 reports (that level must be
       unique and come from at least 2 reports), or
    2. the same non-normal level in the last 2 reports too (3 shifts in a row).
    """
    alerts = []
    for row in items:
        item, level = row["item"], row.get("level")
        if row["value"] is None or level is None or row.get("quote_verified") is not True:
            continue
        if is_normal(item, level):
            continue
        past = _levels(history, item)
        seen = [lv for lv in past if lv is not None]
        refs = [r for r in ([report_id] if report_id else [])] + [
            history_report_ids[n] for n, lv in enumerate(past) if lv is not None and n < len(history_report_ids)]
        label = ITEM_LABELS[item]
        shown = LEVEL_LABELS.get(item, {}).get(level, level)

        if len(past) >= 2 and past[0] == level and past[1] == level:
            alerts.append(_alert(
                "change", item, f"{label.capitalize()}: {shown}, 3 turnos seguidos.", refs,
                quote=row["quote"], verified=True))
            continue
        if len(seen) >= 2:
            ranked = Counter(seen).most_common()
            unique_mode = len(ranked) == 1 or ranked[0][1] > ranked[1][1]
            if unique_mode and ranked[0][0] != level:
                usual = LEVEL_LABELS.get(item, {}).get(ranked[0][0], ranked[0][0])
                alerts.append(_alert(
                    "change", item, f"{label.capitalize()}: {shown} (lo habitual era: {usual}).", refs,
                    quote=row["quote"], verified=True))
    return alerts


# --- entry point -------------------------------------------------------------------------


def compare(items: list[dict], plan: CarePlan | None, history: list[list[dict]], *,
            report_id: str | None = None, history_report_ids: list[str] | None = None,
            include_changes: bool = True) -> list[dict]:
    """All code-computed alerts for one report.

    items: contract-shaped item dicts of this report (item, value, level, details,
    quote, quote_verified). history: items of previous shift reports of the same
    patient, newest first, parallel to `history_report_ids`.
    """
    alerts = missing_alerts(items, report_id)
    alerts += omission_alerts(items, plan, report_id)
    if include_changes:
        alerts += change_alerts(items, history, report_id, history_report_ids or [])
    return alerts
