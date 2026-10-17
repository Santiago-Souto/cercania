import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Alert, ReportVersion
from test_process import (  # noqa: F401  (db is a fixture)
    CG, DOC, FALL, FAM, REPORT, db, extract_client, fall_triage, happy_extract, run,
)


@pytest.fixture()
def client(db, monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADER", "1")
    return TestClient(app)


def correct(client, report_id, corrections, person=CG):
    return client.post(f"/reports/{report_id}/corrections", json={"corrections": corrections},
                       headers={"X-Person-Id": person})


def test_correction_creates_version_2_and_keeps_version_1(client, db):
    original = run(REPORT, e=happy_extract())
    rid = original["report"]["id"]
    resp = correct(client, rid, [{"item": "sleep", "value": "Durmió bien"},
                                 {"item": "appetite", "value": "Comió normal"}])
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 2 and body["id"] == rid
    by_item = {i["item"]: i for i in body["items"]}
    assert by_item["sleep"] == {**by_item["sleep"], "value": "Durmió bien", "level": None, "quote": None,
                                "quote_verified": None, "source": "correction"}
    assert by_item["appetite"]["value"] == "Comió normal" and by_item["appetite"]["source"] == "correction"
    # untouched items are copied with their evidence
    assert by_item["urination"]["quote"] == "Orinó bien" and by_item["urination"]["source"] == "transcript"
    assert by_item["medication"]["details"]["doses"]
    assert body["missing_items"] == ["mood", "mobility", "pain"]
    assert {a["item"] for a in body["alerts"] if a["type"] == "missing_item"} == {"mood", "mobility", "pain"}
    # the appetite change alert was about a corrected item: dropped; omissions recomputed
    assert not [a for a in body["alerts"] if a["type"] == "change"]
    assert len([a for a in body["alerts"] if a["type"] == "omission"]) == 2

    with db() as s:
        versions = s.scalars(select(ReportVersion).where(ReportVersion.report_id == rid)
                             .order_by(ReportVersion.version)).all()
        assert [v.version for v in versions] == [1, 2]
        assert versions[1].created_by == CG and versions[1].source.value == "correction"
        v1 = {i.item.value: i for i in versions[0].items}
        assert v1["sleep"].value is None and v1["appetite"].value == "Comió poco en la cena"
        assert v1["appetite"].quote_verified is True
        assert len([a for a in versions[0].alerts if a.type.value == "change"]) == 1


def test_correction_can_mark_item_not_mentioned(client):
    rid = run(REPORT, e=happy_extract())["report"]["id"]
    body = correct(client, rid, [{"item": "urination", "value": None}]).json()
    assert "urination" in body["missing_items"]


def test_family_cannot_correct(client):
    rid = run(REPORT, e=happy_extract())["report"]["id"]
    assert correct(client, rid, [{"item": "sleep", "value": "x"}], person=FAM).status_code == 403
    assert correct(client, rid, [{"item": "sleep", "value": "x"}], person=DOC).status_code == 403


def test_emergency_report_is_not_correctable(client):
    rid = run(FALL, sender=FAM, t=fall_triage())["report"]["id"]
    resp = correct(client, rid, [{"item": "sleep", "value": "x"}], person=CG)
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "not_correctable"


def test_emergency_alert_carries_over_with_notifications(client, db):
    result = run(FALL, t=fall_triage(), e=extract_client())
    rid = result["report"]["id"]
    with db() as s:
        alert = s.scalar(select(Alert).where(Alert.type == "emergency"))
        alert.notifications = [{"to": "caregiver", "person_id": "cg_002", "status": "sent", "error": None}]
        s.commit()
    body = correct(client, rid, [{"item": "sleep", "value": "Durmió bien"}]).json()
    [emergency] = [a for a in body["alerts"] if a["type"] == "emergency"]
    assert emergency["report_version"] == 2 and emergency["evidence_quote"]
    assert emergency["notifications"][0]["status"] == "sent"
    assert body["red_flag"] is True


def test_unknown_report_and_bad_body(client):
    assert correct(client, "rep_nope", [{"item": "sleep", "value": "x"}]).status_code == 404
    rid = run(REPORT, e=happy_extract())["report"]["id"]
    assert correct(client, rid, []).status_code == 422
    assert correct(client, rid, [{"item": "nonsense", "value": "x"}]).status_code == 422
