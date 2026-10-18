"""Message -> emergency yes/no, with the reason and a verbatim quote.

The one place where the model decides (AGENTS.md section 3): whether a message
describes a patient who needs immediate help. Everything around that decision is
code:
- the quote is verified against the message like any other quote, but an
  unverified quote never turns an emergency off (it is only shown as unverified);
- the reply text is fixed here, never written by the model;
- who gets notified comes from the database (models.emergency_recipients).

Runs for every message from a registered sender, in every role, separately from
extract.py. It never raises: a model failure returns status "failed" so the
caller can still store the report and send the fixed emergency line.

The emergency criteria in SYSTEM_PROMPT are provisional (AGENTS.md section 16).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import llm
from .extract import verify_quote
from .models import Role, TriageStatus

# TRIAGE_MODEL="<provider>:<model>" switches vendor; see llm.py.
DEFAULT_MODEL = "anthropic:claude-haiku-5-5"
MAX_TOKENS = 500
TIMEOUT_SEC = 10.0

# Fixed texts (code, not model). Sent to the sender as-is.
EMERGENCY_REPLY = (
    "Esto parece una emergencia. Llamá ya a emergencias o al médico. "
    "Estamos avisando a los contactos registrados del paciente."
)
TRIAGE_FAILED_LINE = (
    "No pudimos revisar el mensaje automáticamente. "
    "Si es una emergencia, llamá ya a emergencias o al médico."
)

SYSTEM_PROMPT = """\
You read one message about a dependent patient (usually an older adult) and decide whether it
describes an EMERGENCY: the patient needs immediate help or their health or life is at risk now.
The message is a speech-to-text transcript or a typed text, usually in Spanish (Rioplatense slang
is common). It may come from a caregiver, a family member, the doctor or the patient themself
(then "I" is the patient).

Examples of emergencies: a fall with injury, a fall where the patient cannot get up, or a fall not
yet checked by anyone; chest pain; difficulty breathing; unconsciousness or not responding; sudden
confusion, slurred speech or weakness on one side; heavy bleeding; choking; seizures; a wrong or
double medication dose; the patient missing or lost; the patient saying they need help now.

Not emergencies: negated mentions ("sin caídas", "no se cayó"); routine reports with nothing
alarming; an event the message says was already attended and the patient is now fine.

Rules:
- If it is unclear whether the patient still needs help, answer emergency = true.
  A false alarm costs less than a missed emergency.
- reason: one short sentence in the message's language saying what happened. null if not an emergency.
- quote: copy verbatim from the message the words that show the emergency: one contiguous fragment,
  same words, no paraphrasing. null if not an emergency.
- Never diagnose and never give medical instructions. Only classify.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "emergency": {"type": "boolean"},
        "reason": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "quote": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["emergency", "reason", "quote"],
    "additionalProperties": False,
}


@dataclass
class Triage:
    status: TriageStatus
    emergency: bool
    reason: str | None = None
    quote: str | None = None
    quote_verified: bool | None = None
    model: str | None = None
    raw: dict | None = None  # model output as returned, kept as evidence
    error: str | None = None  # why it failed; for logs, not for the sender

    @property
    def reply(self) -> str | None:
        """Fixed text to send the sender first, or None if no emergency line is needed."""
        if self.status is TriageStatus.failed:
            return TRIAGE_FAILED_LINE
        return EMERGENCY_REPLY if self.emergency else None

    def as_contract(self) -> dict:
        """`triage` object of ProcessResult (docs/contract.md)."""
        return {"status": self.status.value, "emergency": self.emergency, "reason": self.reason,
                "quote": self.quote, "quote_verified": self.quote_verified}


def _failed(error: str, model: str | None = None) -> Triage:
    return Triage(status=TriageStatus.failed, emergency=False, model=model, error=error)


# --- Validation of model output (code, no model) ------------------------------------


def _text(value) -> str | None:
    """Model strings are trusted only if they are strings; anything else counts as absent."""
    return value.strip() or None if isinstance(value, str) else None


def validate(raw: dict, text: str, model: str | None = None) -> Triage:
    emergency = raw.get("emergency")
    if not isinstance(emergency, bool):
        return _failed(f"emergency is not a boolean: {emergency!r}", model)
    if not emergency:
        # Nothing to explain; drop anything the model added.
        return Triage(status=TriageStatus.ok, emergency=False, model=model, raw=raw)

    reason = _text(raw.get("reason"))
    quote = _text(raw.get("quote"))
    # The emergency stands even if the quote is missing or not found.
    return Triage(
        status=TriageStatus.ok,
        emergency=True,
        reason=reason,
        quote=quote,
        quote_verified=verify_quote(quote, text) if quote is not None else None,
        model=model,
        raw=raw,
    )


# --- Model call ---------------------------------------------------------------------


def _user_message(text: str, sender_role: Role | None) -> str:
    sender = sender_role.value if sender_role is not None else "unknown"
    return f"Sender role: {sender}\n\nMessage:\n<message>\n{text}\n</message>"


def triage(text: str, *, sender_role: Role | None = None, client=None,
           model: str | None = None) -> Triage:
    """Classify one message. Never raises; on any failure returns status "failed".

    The catch-all is deliberate: whatever goes wrong, the caller must still store
    the report and send TRIAGE_FAILED_LINE (AGENTS.md section 4.2).
    """
    if not isinstance(text, str) or not text.strip():
        return _failed("empty message")

    model = model or os.environ.get("TRIAGE_MODEL") or DEFAULT_MODEL
    try:
        provider, name = llm.parse_model(model)
        model = f"{provider}:{name}"
        return _classify(text, sender_role, client, model)
    except Exception as e:  # noqa: BLE001 - see docstring
        return _failed(f"{type(e).__name__}: {e}", model)


def _classify(text: str, sender_role: Role | None, client, model: str) -> Triage:
    try:
        raw = llm.complete_json(
            system=SYSTEM_PROMPT,
            user=_user_message(text, sender_role),
            schema=SCHEMA,
            model=model,
            max_tokens=MAX_TOKENS,
            timeout=TIMEOUT_SEC,
            effort="low",  # the emergency reply must go out first
            client=client,
        )
    except llm.LLMError as e:
        return _failed(str(e), model)
    return validate(raw, text, model)
