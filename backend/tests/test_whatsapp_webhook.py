import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app import whatsapp
from app.main import app

client = TestClient(app)


def payload(*messages):
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {"messages": list(messages)}}]}],
    }


def voice(message_id="wamid.1", sender="5491122334455"):
    return {
        "id": message_id,
        "from": sender,
        "type": "audio",
        "audio": {"id": "media-1", "mime_type": "audio/ogg; codecs=opus", "voice": True},
    }


def post_signed(body: dict, secret="app-secret"):
    raw = json.dumps(body).encode()
    signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(
        "/webhook/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"},
    )


def test_verify_handshake_echoes_challenge():
    r = client.get(
        "/webhook/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"},
    )
    assert r.status_code == 200
    assert r.text == "12345"


def test_verify_handshake_rejects_wrong_token():
    r = client.get(
        "/webhook/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "12345"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "verification_failed"


def test_rejects_unsigned_and_badly_signed_requests(monkeypatch):
    handled = []
    monkeypatch.setattr(whatsapp, "handle_message", handled.append)
    assert client.post("/webhook/whatsapp", json=payload(voice())).status_code == 403
    assert post_signed(payload(voice()), secret="wrong").status_code == 403
    assert handled == []


def test_acks_and_hands_message_to_background(monkeypatch):
    handled = []
    monkeypatch.setattr(whatsapp, "handle_message", handled.append)
    r = post_signed(payload(voice()))
    assert r.status_code == 200
    assert r.json() == {"status": "received"}
    assert [m.id for m in handled] == ["wamid.1"]
    assert handled[0].audio_id == "media-1"


def test_duplicate_delivery_is_processed_once(monkeypatch):
    handled = []
    monkeypatch.setattr(whatsapp, "handle_message", handled.append)
    assert post_signed(payload(voice())).status_code == 200
    assert post_signed(payload(voice())).status_code == 200
    assert len(handled) == 1


def test_status_updates_are_acked_and_ignored(monkeypatch):
    handled = []
    monkeypatch.setattr(whatsapp, "handle_message", handled.append)
    status_only = {"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.1", "status": "read"}]}}]}]}
    assert post_signed(status_only).status_code == 200
    assert handled == []
