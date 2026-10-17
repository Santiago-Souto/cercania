import json
import os
from types import SimpleNamespace

import pytest

from app.extract import (
    ExtractionError,
    ITEM_LEVELS,
    build_schema,
    extract,
    normalize,
    validate,
    verify_quote,
)
from app.models import ChecklistItem

MEDS = [
    {"id": "med_001", "name": "Enalapril", "times": ["08:00", "20:00"]},
    {"id": "med_002", "name": "Metformina", "times": ["08:00"]},
]
TRANSCRIPT = (
    "Hoy Rosa casi no comió nada en la cena. Le di el enalapril a las ocho. "
    "Se quejó de la rodilla, no sé qué más."
)


def empty_raw() -> dict:
    raw = {}
    for item, levels in ITEM_LEVELS.items():
        raw[item.value] = {"value": None, "quote": None}
        if levels is not None:
            raw[item.value]["level"] = None
    raw["medication"]["doses"] = []
    return raw


# --- normalization and quote verification ---------------------------------------


def test_normalize_ignores_case_accents_punctuation_whitespace():
    assert normalize("  Casi NO comió,   nada!  ") == "casi no comio nada"


def test_verify_quote_accepts_normalized_substring():
    assert verify_quote("casi no comio nada en la cena", TRANSCRIPT)
    assert verify_quote("Se quejó de la rodilla", TRANSCRIPT)


def test_verify_quote_rejects_paraphrase_and_partial_words():
    assert not verify_quote("comió poco en la cena", TRANSCRIPT)
    assert not verify_quote("ocho. Se quej", TRANSCRIPT)  # "quej" is not a whole word
    assert not verify_quote("", TRANSCRIPT)
    assert not verify_quote(None, TRANSCRIPT)


# --- schema --------------------------------------------------------------------


def test_schema_covers_every_checklist_item_and_is_strict():
    schema = build_schema(MEDS)
    assert set(schema["required"]) == {i.value for i in ChecklistItem}
    assert schema["additionalProperties"] is False
    for item in ChecklistItem:
        sub = schema["properties"][item.value]
        assert sub["additionalProperties"] is False
        assert set(sub["required"]) == set(sub["properties"])


def test_schema_limits_doses_to_care_plan():
    dose = build_schema(MEDS)["properties"]["medication"]["properties"]["doses"]["items"]
    assert dose["properties"]["plan_ref"]["enum"] == ["med_001", "med_002"]
    assert dose["properties"]["time"]["enum"] == ["08:00", "20:00"]


# --- validation of model output ------------------------------------------------


def test_validate_not_mentioned_items_are_null():
    items, warnings = validate(empty_raw(), TRANSCRIPT, MEDS)
    assert [i["item"] for i in items] == [i.value for i in ChecklistItem]
    assert all(i["value"] is None and i["quote"] is None and i["quote_verified"] is None for i in items)
    assert warnings == []


def test_validate_marks_unverified_quote_but_keeps_value():
    raw = empty_raw()
    raw["appetite"] = {"value": "Comió poco", "level": "low", "quote": "comió poco en la cena"}
    raw["pain"] = {"value": "Dolor de rodilla", "level": "present", "quote": "Se quejó de la rodilla"}
    items = {i["item"]: i for i in validate(raw, TRANSCRIPT, MEDS)[0]}
    assert items["appetite"]["quote_verified"] is False
    assert items["appetite"]["value"] == "Comió poco"
    assert items["pain"]["quote_verified"] is True


def test_validate_drops_unknown_levels_and_off_plan_doses():
    raw = empty_raw()
    raw["mood"] = {"value": "Rara", "level": "weird", "quote": "no sé qué más"}
    raw["medication"] = {
        "value": "Enalapril 08:00",
        "quote": "Le di el enalapril a las ocho",
        "doses": [
            {"plan_ref": "med_001", "time": "08:00", "given": True, "quote": "Le di el enalapril a las ocho"},
            {"plan_ref": "med_002", "time": "20:00", "given": True, "quote": "a las ocho"},
            {"plan_ref": "med_999", "time": "08:00", "given": True, "quote": "a las ocho"},
        ],
    }
    items, warnings = validate(raw, TRANSCRIPT, MEDS)
    items = {i["item"]: i for i in items}
    assert items["mood"]["level"] is None
    assert items["medication"]["level"] is None
    assert items["medication"]["details"] == {"doses": [
        {"plan_ref": "med_001", "time": "08:00", "given": True,
         "quote": "Le di el enalapril a las ocho", "quote_verified": True},
    ]}
    assert len(warnings) == 3


def test_validate_clears_quote_when_value_is_null():
    raw = empty_raw()
    raw["sleep"] = {"value": None, "level": "poor", "quote": "durmió mal"}
    sleep = next(i for i in validate(raw, TRANSCRIPT, MEDS)[0] if i["item"] == "sleep")
    assert sleep["level"] is None and sleep["quote"] is None and sleep["quote_verified"] is None


# --- model call wiring (fake client: tests only, never used by the app) ----------


class FakeClient:
    def __init__(self, text: str | None = None, stop_reason: str = "end_turn"):
        self.calls = []
        content = [SimpleNamespace(type="text", text=text)] if text is not None else []
        self._response = SimpleNamespace(stop_reason=stop_reason, content=content)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_extract_sends_schema_and_returns_validated_items():
    raw = empty_raw()
    raw["appetite"] = {"value": "Casi no comió", "level": "low", "quote": "casi no comió nada en la cena"}
    client = FakeClient(json.dumps(raw))
    result = extract(TRANSCRIPT, MEDS, client=client, model="test-model")
    call = client.calls[0]
    assert call["model"] == "test-model"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "Enalapril" in call["messages"][0]["content"]
    assert result.items[0]["quote_verified"] is True
    assert "appetite" not in result.missing_items
    assert result.raw == raw


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_extract_raises_clear_error_on_bad_stop(stop_reason):
    with pytest.raises(ExtractionError) as e:
        extract(TRANSCRIPT, MEDS, client=FakeClient("{}", stop_reason=stop_reason))
    assert e.value.message


@pytest.mark.parametrize("text", ["[1, 2]", '"texto"', "42", "null"])
def test_extract_raises_extraction_error_on_non_object_json(text):
    with pytest.raises(ExtractionError):
        extract(TRANSCRIPT, MEDS, client=FakeClient(text))


def test_validate_drops_wrong_types_instead_of_raising():
    raw = empty_raw()
    raw["sleep"] = "durmió mal"  # not an object
    raw["mood"] = {"value": 7, "level": ["low"], "quote": None}
    raw["medication"] = {
        "value": "Enalapril", "quote": "Le di el enalapril a las ocho",
        "doses": ["med_001", {"plan_ref": 1, "time": "08:00"},
                  {"plan_ref": "med_001", "time": "08:00", "given": "sí",
                   "quote": "Le di el enalapril a las ocho"}],
    }
    items, warnings = validate(raw, TRANSCRIPT, MEDS)
    items = {i["item"]: i for i in items}
    assert items["sleep"]["value"] is None and items["mood"]["value"] is None
    assert items["medication"]["details"]["doses"] == [
        {"plan_ref": "med_001", "time": "08:00", "given": None,
         "quote": "Le di el enalapril a las ocho", "quote_verified": True}]
    assert len(warnings) == 3


def test_extract_raises_on_invalid_json_and_empty_transcript():
    with pytest.raises(ExtractionError):
        extract(TRANSCRIPT, MEDS, client=FakeClient("not json"))
    with pytest.raises(ExtractionError):
        extract("   ", MEDS, client=FakeClient("{}"))


# --- live call (needs ANTHROPIC_API_KEY) -------------------------------------------


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_live_extraction_unseen_transcript():
    transcript = (
        "Bueno, Rosa hoy anduvo medio bajoneada. A la mañana le di el enalapril y la metformina, "
        "a la noche no le di nada porque se durmió temprano. Almorzó todo. Se cayó en el baño "
        "pero no se lastimó."
    )
    result = extract(transcript, MEDS)
    items = {i["item"]: i for i in result.items}
    assert items["incidents"]["value"] is not None and items["incidents"]["level"] == "present"
    assert items["appetite"]["level"] == "normal"
    assert items["pain"]["value"] is None
    assert all(i["quote_verified"] for i in result.items if i["value"] is not None), result.warnings
