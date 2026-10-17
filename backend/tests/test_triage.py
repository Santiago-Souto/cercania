import json
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Base,
    Patient,
    PatientAccess,
    Person,
    Role,
    TriageStatus,
    emergency_recipients,
)
from app.triage import EMERGENCY_REPLY, TRIAGE_FAILED_LINE, triage, validate

TEXT = "Rosa se cayó en el baño hace un rato y no se puede levantar, le duele la cadera."


# --- validation of model output ------------------------------------------------


def test_validate_emergency_with_verified_quote():
    t = validate({"emergency": True, "reason": "Caída sin poder levantarse",
                  "quote": "se cayó en el baño hace un rato y no se puede levantar"}, TEXT)
    assert t.status is TriageStatus.ok and t.emergency
    assert t.quote_verified is True
    assert t.reply == EMERGENCY_REPLY


def test_unverified_or_missing_quote_never_turns_emergency_off():
    t = validate({"emergency": True, "reason": "Caída", "quote": "se golpeó la cabeza"}, TEXT)
    assert t.emergency and t.quote_verified is False and t.reply == EMERGENCY_REPLY
    t = validate({"emergency": True, "reason": None, "quote": None}, TEXT)
    assert t.emergency and t.quote is None and t.quote_verified is None


def test_validate_no_emergency_drops_reason_and_quote():
    t = validate({"emergency": False, "reason": "algo", "quote": "Rosa"}, TEXT)
    assert t.status is TriageStatus.ok and not t.emergency
    assert t.reason is None and t.quote is None and t.quote_verified is None
    assert t.reply is None


def test_validate_non_boolean_emergency_is_a_failure():
    t = validate({"emergency": "yes", "reason": None, "quote": None}, TEXT)
    assert t.status is TriageStatus.failed and t.reply == TRIAGE_FAILED_LINE


def test_as_contract_shape():
    t = validate({"emergency": False, "reason": None, "quote": None}, TEXT)
    assert t.as_contract() == {"status": "ok", "emergency": False, "reason": None,
                               "quote": None, "quote_verified": None}


# --- model call wiring (fake client: tests only, never used by the app) ----------


class FakeClient:
    def __init__(self, text: str | None = None, stop_reason: str = "end_turn", exc=None):
        self.calls = []
        content = [SimpleNamespace(type="text", text=text)] if text is not None else []
        self._response = SimpleNamespace(stop_reason=stop_reason, content=content)
        self._exc = exc
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._response


def test_triage_sends_schema_and_sender_role():
    out = {"emergency": True, "reason": "Caída", "quote": "no se puede levantar"}
    client = FakeClient(json.dumps(out))
    t = triage(TEXT, sender_role=Role.family, client=client, model="test-model")
    call = client.calls[0]
    assert call["model"] == "test-model"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "Sender role: family" in call["messages"][0]["content"]
    assert t.emergency and t.quote_verified and t.raw == out


@pytest.mark.parametrize("client", [
    FakeClient("{}", stop_reason="refusal"),
    FakeClient("{}", stop_reason="max_tokens"),
    FakeClient("not json"),
    FakeClient("[1, 2]"),
])
def test_triage_never_raises_on_bad_output(client):
    t = triage(TEXT, client=client)
    assert t.status is TriageStatus.failed and not t.emergency
    assert t.reply == TRIAGE_FAILED_LINE and t.error


def test_triage_never_raises_on_api_error():
    import anthropic

    t = triage(TEXT, client=FakeClient(exc=anthropic.APIConnectionError(request=None)))
    assert t.status is TriageStatus.failed and t.reply == TRIAGE_FAILED_LINE


def test_non_string_reason_or_quote_counts_as_absent_and_keeps_emergency():
    t = validate({"emergency": True, "reason": 42, "quote": ["se cayó"]}, TEXT)
    assert t.status is TriageStatus.ok and t.emergency
    assert t.reason is None and t.quote is None and t.reply == EMERGENCY_REPLY


def test_triage_never_raises_on_unexpected_errors():
    t = triage(TEXT, client=FakeClient(exc=RuntimeError("boom")))
    assert t.status is TriageStatus.failed and t.reply == TRIAGE_FAILED_LINE
    # Response object missing fields entirely.
    broken = FakeClient("{}")
    broken._response = object()
    assert triage(TEXT, client=broken).status is TriageStatus.failed


def test_triage_empty_message_fails_without_calling_model():
    client = FakeClient("{}")
    assert triage("  ", client=client).status is TriageStatus.failed
    assert client.calls == []


# --- who gets notified (code, no model) ------------------------------------------


def make_session(provider_phone: str | None) -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    s.add(Patient(id="pat_x", display_name="Test (ficticio)",
                  health_provider_name="Prestador (ficticio)" if provider_phone else None,
                  health_provider_phone=provider_phone))
    for pid, role in [("cg1", Role.caregiver), ("cg2", Role.caregiver), ("fam", Role.family),
                      ("doc", Role.doctor), ("pt", Role.patient)]:
        s.add(Person(id=pid, phone=f"+1555010{len(pid)}{pid}", display_name=pid))
        s.add(PatientAccess(person_id=pid, patient_id="pat_x", role=role))
    s.commit()
    return s


def test_recipients_are_provider_caregivers_and_family_minus_sender():
    s = make_session("+15550100041")
    got = emergency_recipients(s, "pat_x", sender_id="cg1")
    assert [(r["to"], r["person_id"]) for r in got] == [
        ("health_provider", None), ("caregiver", "cg2"), ("family", "fam")]


def test_recipients_never_include_patient_or_doctor_and_skip_missing_provider():
    s = make_session(None)
    got = emergency_recipients(s, "pat_x", sender_id="pt")
    assert [r["person_id"] for r in got] == ["cg1", "cg2", "fam"]


# --- live call (needs ANTHROPIC_API_KEY) -------------------------------------------


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
@pytest.mark.parametrize("text,role,expected", [
    ("Che, Jorge se fue al piso en el pasillo y no responde, está pálido.", Role.caregiver, True),
    ("Me caí y no me puedo levantar, ayuda por favor.", Role.patient, True),
    ("Turno tranquilo, comió bien, durmió la siesta, sin caídas ni dolores.", Role.caregiver, False),
])
def test_live_triage(text, role, expected):
    t = triage(text, sender_role=role)
    assert t.status is TriageStatus.ok, t.error
    assert t.emergency is expected
    if expected:
        assert t.quote_verified, t.quote
