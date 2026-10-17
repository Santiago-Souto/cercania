"""Transcript -> checklist items, each backed by a verbatim quote.

The model only reads: it fills one JSON schema (structured output) with what the
caregiver said, quoting the transcript. Code then decides what to trust:
- every quote is checked against the transcript (normalized substring match);
- levels outside the allowed set are dropped;
- medication doses may only reference medications and times in the care plan.

Nothing here computes doses, schedules or alerts; compare.py does the comparing.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .models import ChecklistItem

# Haiku: one schema-constrained call, no tools; code verifies every quote (AGENTS.md section 8).
DEFAULT_MODEL = "claude-haiku-5-5"
MAX_TOKENS = 4000
TIMEOUT_SEC = 20.0

# Coarse categories compare.py uses to detect changes over time. `None` = item has no level.
ITEM_LEVELS: dict[ChecklistItem, tuple[str, ...] | None] = {
    ChecklistItem.appetite: ("normal", "low", "none"),
    ChecklistItem.sleep: ("normal", "poor"),
    ChecklistItem.urination: ("normal", "low", "none"),
    ChecklistItem.medication: None,  # structured in details.doses instead
    ChecklistItem.mood: ("normal", "low", "agitated", "confused"),
    ChecklistItem.mobility: ("normal", "reduced", "none"),
    ChecklistItem.pain: ("none", "present"),
    ChecklistItem.incidents: ("none", "present"),
}

SYSTEM_PROMPT = """\
You turn a caregiver's end-of-shift report about one patient into a fixed checklist.
The report is a speech-to-text transcript, usually in Spanish (Rioplatense slang is common).

Rules:
- Only record what the transcript says. Never infer, assume or fill gaps.
- If an item is not mentioned, set value, level and quote to null.
- quote must be copied verbatim from the transcript: one contiguous fragment, same words,
  no paraphrasing, no joining separate fragments. Keep it short (the words that support the value).
- value is a short summary in the transcript's language (e.g. "Comió poco en la cena").
- level is a coarse category from the allowed list. If the item is mentioned but the category
  is unclear, set level to null and describe what was said in value.
- incidents covers falls, injuries or unusual events; "sin novedades" / "sin caídas" means level "none".
- medication: list one dose per medication and plan time the report talks about, using the
  plan_ref and time from the care plan below. given is true if it was given/taken, false if the
  report says it was not, null if unclear. Do not list doses the report does not mention.
  Never compute or suggest doses.
"""


class ExtractionError(Exception):
    """The model call failed. `message` is safe to show to the caregiver."""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.message = message
        self.retryable = retryable


@dataclass
class Extraction:
    items: list[dict]  # one per ChecklistItem, in enum order, contract shape + details
    raw: dict  # model output as returned, for report_version.extraction_raw
    model: str
    warnings: list[str] = field(default_factory=list)

    @property
    def missing_items(self) -> list[str]:
        return [i["item"] for i in self.items if i["value"] is None]


# --- Quote verification (code, no model) -------------------------------------------


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w]+", " ", text)
    return " ".join(text.split())


def verify_quote(quote: str | None, transcript: str) -> bool:
    """True if `quote` appears in `transcript` as whole words, after normalization."""
    q = normalize(quote or "")
    return bool(q) and f" {q} " in f" {normalize(transcript)} "


# --- Schema -------------------------------------------------------------------------


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def build_schema(medications: list[dict]) -> dict:
    """JSON schema for one report. `medications`: [{"id", "name", "times"}] from the care plan."""
    med_ids = [m["id"] for m in medications]
    times = sorted({t for m in medications for t in m["times"]})
    dose = {
        "type": "object",
        "properties": {
            "plan_ref": {"type": "string", "enum": med_ids} if med_ids else {"type": "string"},
            "time": {"type": "string", "enum": times} if times else {"type": "string"},
            "given": _nullable({"type": "boolean"}),
            "quote": {"type": "string"},
        },
        "required": ["plan_ref", "time", "given", "quote"],
        "additionalProperties": False,
    }
    properties = {}
    for item, levels in ITEM_LEVELS.items():
        props: dict[str, Any] = {
            "value": _nullable({"type": "string"}),
            "quote": _nullable({"type": "string"}),
        }
        if levels is not None:
            props["level"] = _nullable({"type": "string", "enum": list(levels)})
        if item is ChecklistItem.medication:
            props["doses"] = {"type": "array", "items": dose}
        properties[item.value] = {
            "type": "object",
            "properties": props,
            "required": list(props),
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


# --- Validation of model output (code, no model) ------------------------------------


def _text(value) -> str | None:
    """Model strings are trusted only if they are strings; anything else counts as absent."""
    return value.strip() or None if isinstance(value, str) else None


def validate(raw: dict, transcript: str, medications: list[dict]) -> tuple[list[dict], list[str]]:
    """Turn raw model output into contract-shaped items. Never trusts the model blindly.

    Wrong types (possible if EXTRACT_MODEL points at a model without structured
    output) are dropped with a warning, never raised.
    """
    plan_slots = {(m["id"], t) for m in medications for t in m["times"]}
    items: list[dict] = []
    warnings: list[str] = []

    for item, levels in ITEM_LEVELS.items():
        got = raw.get(item.value) or {}
        if not isinstance(got, dict):
            warnings.append(f"{item.value}: expected an object, got {type(got).__name__}; dropped")
            got = {}
        value = _text(got.get("value"))
        quote = _text(got.get("quote"))
        level = got.get("level") if isinstance(got.get("level"), str) else None
        details = None

        if value is None:
            # Not mentioned: nothing else may be set.
            quote = level = None
        if levels is None or level not in levels:
            if level is not None:
                warnings.append(f"{item.value}: level {level!r} not allowed; dropped")
            level = None

        quote_verified = verify_quote(quote, transcript) if value is not None else None
        if value is not None and not quote_verified:
            warnings.append(f"{item.value}: quote not found in transcript: {quote!r}")

        if item is ChecklistItem.medication and value is not None:
            doses = []
            raw_doses = got.get("doses")
            for d in raw_doses if isinstance(raw_doses, list) else []:
                if not isinstance(d, dict):
                    warnings.append(f"medication: dose is not an object: {d!r}; dropped")
                    continue
                slot = (d.get("plan_ref"), d.get("time"))
                if not all(isinstance(x, str) for x in slot) or slot not in plan_slots:
                    warnings.append(f"medication: dose {slot[0]!r} {slot[1]!r} not in care plan; dropped")
                    continue
                given = d.get("given")
                dose_quote = _text(d.get("quote"))
                doses.append({
                    "plan_ref": slot[0],
                    "time": slot[1],
                    "given": given if isinstance(given, bool) else None,  # anything else = unclear
                    "quote": dose_quote,
                    "quote_verified": verify_quote(dose_quote, transcript),
                })
            details = {"doses": doses}

        items.append({
            "item": item.value,
            "value": value,
            "level": level,
            "details": details,
            "quote": quote,
            "quote_verified": quote_verified,
        })
    return items, warnings


# --- Model call ---------------------------------------------------------------------


def plan_medications(care_plan) -> list[dict]:
    """Care plan ORM object -> the plain dicts extract() needs."""
    if care_plan is None:
        return []
    return [{"id": m.id, "name": m.name, "times": list(m.times)} for m in care_plan.medications]


def _user_message(transcript: str, medications: list[dict]) -> str:
    plan = "\n".join(
        f"- plan_ref={m['id']}: {m['name']} at {', '.join(m['times'])}" for m in medications
    ) or "- (no medications in the care plan)"
    return f"Care plan medications:\n{plan}\n\nTranscript:\n<transcript>\n{transcript}\n</transcript>"


def _default_client():
    import anthropic

    try:
        return anthropic.Anthropic(timeout=TIMEOUT_SEC, max_retries=1)
    except anthropic.AnthropicError as e:
        raise ExtractionError(
            "El servicio de IA no está configurado (falta ANTHROPIC_API_KEY).", retryable=False
        ) from e


def extract(transcript: str, medications: list[dict], *, client=None, model: str | None = None) -> Extraction:
    """Extract checklist items from a transcript. Raises ExtractionError on any model failure."""
    import anthropic

    if not transcript or not transcript.strip():
        raise ExtractionError("El reporte llegó vacío; no hay nada para registrar.", retryable=False)

    model = model or os.environ.get("EXTRACT_MODEL") or DEFAULT_MODEL
    client = client or _default_client()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _user_message(transcript, medications)}],
            output_config={
                "effort": "low",  # latency budget: confirmation in < 10 s
                "format": {"type": "json_schema", "schema": build_schema(medications)},
            },
        )
    except anthropic.AuthenticationError as e:
        raise ExtractionError("El servicio de IA rechazó la credencial configurada.", retryable=False) from e
    except anthropic.BadRequestError as e:
        raise ExtractionError("No pudimos procesar el reporte (solicitud inválida).", retryable=False) from e
    except (anthropic.RateLimitError, anthropic.APITimeoutError, anthropic.APIConnectionError,
            anthropic.InternalServerError, anthropic.APIStatusError) as e:
        raise ExtractionError("El servicio de IA no respondió a tiempo. Volvé a intentar en un momento.") from e

    if response.stop_reason == "refusal":
        raise ExtractionError("El servicio de IA no procesó este reporte.", retryable=False)
    if response.stop_reason == "max_tokens":
        raise ExtractionError("El reporte es demasiado largo para procesarlo de una vez.", retryable=False)

    text = next((b.text for b in response.content if b.type == "text"), None)
    try:
        raw = json.loads(text or "")
    except json.JSONDecodeError as e:
        raise ExtractionError("La respuesta de la IA no tuvo el formato esperado.") from e
    if not isinstance(raw, dict):
        raise ExtractionError("La respuesta de la IA no tuvo el formato esperado.")

    items, warnings = validate(raw, transcript, medications)
    return Extraction(items=items, raw=raw, model=model, warnings=warnings)
