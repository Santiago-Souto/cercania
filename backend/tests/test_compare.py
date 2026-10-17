from types import SimpleNamespace

from app import compare
from app.models import ChecklistItem


def item(name, value=None, level=None, quote=None, verified=None, details=None):
    if value is not None and quote is None:
        quote, verified = value, True
    return {"item": name, "value": value, "level": level, "details": details,
            "quote": quote, "quote_verified": verified}


def all_items(**given):
    rows = {i.value: item(i.value) for i in ChecklistItem}
    rows.update(given)
    return list(rows.values())


def plan():
    meds = [SimpleNamespace(id="med_1", name="Enalapril", times=["08:00", "20:00"])]
    return SimpleNamespace(medications=meds)


def med(doses, verified=True):
    return item("medication", "Enalapril", quote="le di el enalapril", verified=verified,
                details={"doses": doses})


def dose(time, given, verified=True, quote="le di el enalapril"):
    return {"plan_ref": "med_1", "time": time, "given": given, "quote": quote, "quote_verified": verified}


def by_type(alerts, type_):
    return [a for a in alerts if a["type"] == type_]


def test_missing_item_per_null_value():
    alerts = compare.compare(all_items(mood=item("mood", "tranquila", "normal")), None, [], report_id="r1")
    missing = {a["item"] for a in by_type(alerts, "missing_item")}
    assert missing == {i.value for i in ChecklistItem} - {"mood"}
    assert all(a["report_refs"] == ["r1"] for a in alerts)


def test_omission_not_mentioned_not_given_unclear():
    items = all_items(medication=med([dose("08:00", False, quote="no le di")]))
    alerts = by_type(compare.compare(items, plan(), [], report_id="r1"), "omission")
    by_time = {a["detail"].rsplit(":", 1)[0]: a for a in alerts}
    assert by_time["Enalapril 08:00"]["detail"].endswith("no se dio.")
    assert by_time["Enalapril 08:00"]["evidence_quote"] == "no le di"
    assert by_time["Enalapril 08:00"]["evidence_verified"] is True
    assert by_time["Enalapril 08:00"]["plan_ref"] == "med_1"
    assert by_time["Enalapril 20:00"]["detail"].endswith("no se mencionó.")

    items = all_items(medication=med([dose("08:00", None), dose("20:00", True)]))
    alerts = by_type(compare.compare(items, plan(), [], report_id="r1"), "omission")
    assert [a["detail"] for a in alerts] == ["Enalapril 08:00: no está claro."]


def test_medication_not_mentioned_at_all_is_omission_per_dose():
    alerts = by_type(compare.compare(all_items(), plan(), [], report_id="r1"), "omission")
    assert len(alerts) == 2 and all("no se mencionó" in a["detail"] for a in alerts)


def test_all_given_no_omission():
    items = all_items(medication=med([dose("08:00", True), dose("20:00", True)]))
    assert by_type(compare.compare(items, plan(), [], report_id="r1"), "omission") == []


def test_unverified_quote_never_asserts_an_omission():
    items = all_items(medication=med([dose("08:00", False, verified=False), dose("20:00", True)]))
    alerts = by_type(compare.compare(items, plan(), [], report_id="r1"), "omission")
    assert [a["detail"] for a in alerts] == ["Enalapril 08:00: no está claro."]
    assert alerts[0]["evidence_quote"] is None and alerts[0]["evidence_verified"] is None
    # item-level quote unverified: nothing is trusted
    items = all_items(medication=med([dose("08:00", True), dose("20:00", True)], verified=False))
    assert all("no está claro" in a["detail"]
               for a in by_type(compare.compare(items, plan(), [], report_id="r1"), "omission"))


def test_no_omission_for_typed_correction_without_details():
    items = all_items(medication=item("medication", "Tomó todo", quote=None, verified=None))
    assert by_type(compare.compare(items, plan(), [], report_id="r1"), "omission") == []


def hist(*levels, item_name="appetite"):
    return [all_items(**{item_name: item(item_name, "x", lv)}) if lv else all_items() for lv in levels]


def changes(current, history, ids=("h1", "h2", "h3"), item_name="appetite", **kw):
    items = all_items(**{item_name: item(item_name, "x", current, **kw)})
    return by_type(compare.compare(items, None, history, report_id="r0",
                                   history_report_ids=list(ids)), "change")


def test_three_in_a_row():
    alerts = changes("low", hist("low", "low", "normal"))
    assert len(alerts) == 1 and "3 turnos seguidos" in alerts[0]["detail"]
    assert alerts[0]["report_refs"] == ["r0", "h1", "h2", "h3"]
    assert alerts[0]["evidence_quote"] == "x" and alerts[0]["evidence_verified"] is True


def test_differs_from_usual():
    alerts = changes("low", hist("normal", "normal", "normal"))
    assert len(alerts) == 1 and "lo habitual" in alerts[0]["detail"]
    assert len(changes("poor", hist("normal", "normal", "poor", item_name="sleep"), item_name="sleep")) == 1


def test_conservative_cases_do_not_fire():
    assert changes("normal", hist("low", "low", "low")) == []  # back to normal
    assert changes("low", hist("low", "normal", "low")) == []  # usual is mixed: low is the mode
    assert changes("low", hist("normal")) == []  # one data point
    assert changes("low", hist("low", "normal")) == []  # tie, 2 reports
    assert changes("low", []) == []
    assert changes("none", hist("none", "none", "none", item_name="pain"), item_name="pain") == []


def test_unverified_quote_never_produces_change():
    assert changes("low", hist("low", "low", "normal"), verified=False, quote="inventado") == []


def test_pain_present_after_none_is_a_change():
    assert len(changes("present", hist("none", "none", "none", item_name="pain"), item_name="pain")) == 1
