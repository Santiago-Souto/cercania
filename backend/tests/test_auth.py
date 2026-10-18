"""Sign-up / login with a 6-digit SMS code (api/auth.py) and the Twilio sender (sms.py).
Fictional data only; no request reaches Twilio."""

from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import sms
from app.api import auth
from app.deps import SESSION_COOKIE, get_db
from app.main import app
from app.models import (
    Base,
    Invite,
    InviteStatus,
    LoginCode,
    Patient,
    PatientAccess,
    Person,
    Role,
    utcnow,
)

KNOWN = "+15550100001"
NEW = "+15550100009"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = Session(engine)
    s.add(Patient(id="pat_a", display_name="Rosa (ficticia)"))
    s.add(Person(id="cg", phone=KNOWN, display_name="Ana (ficticia)"))
    s.add(PatientAccess(person_id="cg", patient_id="pat_a", role=Role.caregiver))
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    yield s
    app.dependency_overrides.clear()
    s.close()


@pytest.fixture
def texts(monkeypatch):
    """Captures every SMS instead of calling Twilio."""
    sent: list[tuple[str, str]] = []

    def fake_send(to, body, client=None):
        sent.append((to, body))
        return sms.SmsResult(True)

    monkeypatch.setattr(sms, "send_sms", fake_send)
    monkeypatch.delenv("AUTH_DEV_LOG_CODES", raising=False)
    monkeypatch.delenv("ALLOW_DEV_IDENTITY_HEADER", raising=False)
    return sent


@pytest.fixture
def client():
    # https base URL so the Secure cookie is sent back, like in a browser.
    return TestClient(app, base_url="https://testserver")


def code_in(body: str) -> str:
    return next(w for w in body.replace(".", " ").split() if w.isdigit() and len(w) == 6)


def age_codes(db: Session, phone: str, seconds: int) -> None:
    """Moves the phone's codes into the past (to get past the resend limit or expiry)."""
    for row in db.scalars(select(LoginCode).where(LoginCode.phone == phone)):
        row.created_at -= timedelta(seconds=seconds)
        row.expires_at -= timedelta(seconds=seconds)
    db.commit()


# --- Sending ------------------------------------------------------------------------


def test_login_known_phone_texts_a_code(db, texts, client):
    r = client.post("/auth/login", json={"phone": "+1 555 010-0001"})
    assert r.status_code == 200
    assert r.json() == {"status": "code_sent", "phone_last4": "0001",
                        "expires_in_sec": 600, "resend_after_sec": 60}
    assert len(texts) == 1 and texts[0][0] == KNOWN
    row = db.scalar(select(LoginCode).where(LoginCode.phone == KNOWN))
    assert code_in(texts[0][1]) not in row.code_hash  # only the hash is stored


def test_login_unknown_phone_same_answer_and_nothing_sent(db, texts, client):
    r = client.post("/auth/login", json={"phone": NEW})
    assert r.status_code == 200 and r.json()["status"] == "code_sent"
    assert texts == []
    # The rate limit answers the same as for a registered phone.
    assert client.post("/auth/login", json={"phone": NEW}).status_code == 429


def test_invalid_phone(db, texts, client):
    r = client.post("/auth/login", json={"phone": "099123456"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "phone_invalid"


def test_resend_limit_and_hourly_cap(db, texts, client):
    assert client.post("/auth/login", json={"phone": KNOWN}).status_code == 200
    r = client.post("/auth/login", json={"phone": KNOWN})
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_requests"
    for _ in range(4):
        age_codes(db, KNOWN, 61)
        assert client.post("/auth/login", json={"phone": KNOWN}).status_code == 200
    age_codes(db, KNOWN, 61)
    assert client.post("/auth/login", json={"phone": KNOWN}).status_code == 429
    assert len(texts) == 5


def test_signup_known_phone_sends_login_code_and_keeps_person(db, texts, client):
    r = client.post("/auth/signup", json={"name": "Otra persona", "email": "x@example.com", "phone": KNOWN})
    assert r.status_code == 200 and len(texts) == 1
    r = client.post("/auth/verify", json={"phone": KNOWN, "code": code_in(texts[0][1])})
    assert r.status_code == 200
    assert r.json()["user"] == {"id": "cg", "name": "Ana (ficticia)"}
    assert db.scalar(select(Person).where(Person.phone == KNOWN)).display_name == "Ana (ficticia)"


def test_signup_sms_failure_is_reported(db, monkeypatch, client):
    monkeypatch.setattr(sms, "send_sms", lambda to, body, client=None: sms.SmsResult(False, 21608, "unverified"))
    r = client.post("/auth/signup", json={"name": "Nueva", "phone": NEW})
    assert r.status_code == 502 and r.json()["error"]["code"] == "sms_unreachable"


def test_login_sms_failure_still_code_sent(db, monkeypatch, client):
    monkeypatch.setattr(sms, "send_sms", lambda to, body, client=None: sms.SmsResult(False, None, "down"))
    r = client.post("/auth/login", json={"phone": KNOWN})
    assert r.status_code == 200 and r.json()["status"] == "code_sent"


# --- Verifying --------------------------------------------------------------------


def test_signup_verify_creates_person_session_and_accepts_invites(db, texts, client):
    db.add(Invite(patient_id="pat_a", phone=NEW, role=Role.family, invited_by="cg"))
    db.commit()
    client.post("/auth/signup", json={"name": "Nueva (ficticia)", "email": "n@example.com", "phone": NEW})
    assert db.scalar(select(Person).where(Person.phone == NEW)) is None  # not before verify

    r = client.post("/auth/verify", json={"phone": NEW, "code": code_in(texts[0][1])})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["name"] == "Nueva (ficticia)"
    assert body["memberships"] == [{"patient_id": "pat_a", "display_name": "Rosa (ficticia)", "role": "family"}]
    assert db.scalar(select(Invite)).status == InviteStatus.accepted
    cookie = r.headers["set-cookie"]
    assert SESSION_COOKIE in cookie and "HttpOnly" in cookie and "Secure" in cookie
    assert "samesite=none" in cookie.lower()

    me = client.get("/me")
    assert me.status_code == 200 and me.json()["display_name"] == "Nueva (ficticia)"


def test_code_is_single_use(db, texts, client):
    client.post("/auth/login", json={"phone": KNOWN})
    code = code_in(texts[0][1])
    assert client.post("/auth/verify", json={"phone": KNOWN, "code": code}).status_code == 200
    r = client.post("/auth/verify", json={"phone": KNOWN, "code": code})
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_invalid"


def test_new_code_retires_the_previous_one(db, texts, client):
    client.post("/auth/login", json={"phone": KNOWN})
    age_codes(db, KNOWN, 61)
    client.post("/auth/login", json={"phone": KNOWN})
    old, new = code_in(texts[0][1]), code_in(texts[1][1])
    if old != new:
        assert client.post("/auth/verify", json={"phone": KNOWN, "code": old}).status_code == 400
    assert client.post("/auth/verify", json={"phone": KNOWN, "code": new}).status_code == 200


def test_expired_code(db, texts, client):
    client.post("/auth/login", json={"phone": KNOWN})
    age_codes(db, KNOWN, 11 * 60)
    r = client.post("/auth/verify", json={"phone": KNOWN, "code": code_in(texts[0][1])})
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_expired"


def test_locks_after_five_wrong_codes(db, texts, client):
    client.post("/auth/login", json={"phone": KNOWN})
    good = code_in(texts[0][1])
    wrong = "000000" if good != "000000" else "111111"
    codes = [client.post("/auth/verify", json={"phone": KNOWN, "code": wrong}).json()["error"]["code"]
             for _ in range(5)]
    assert codes == ["code_invalid"] * 4 + ["too_many_attempts"]
    r = client.post("/auth/verify", json={"phone": KNOWN, "code": good})
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_attempts"


def test_unknown_phone_cannot_verify(db, texts, client, monkeypatch):
    # Even with the right code (never sent), a login code does not create an account.
    monkeypatch.setattr(auth.secrets, "randbelow", lambda n: 123456)
    client.post("/auth/login", json={"phone": NEW})
    r = client.post("/auth/verify", json={"phone": NEW, "code": "123456"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "code_invalid"
    assert db.scalar(select(Person).where(Person.phone == NEW)) is None


def test_malformed_code_rejected(db, texts, client):
    r = client.post("/auth/verify", json={"phone": KNOWN, "code": "12ab"})
    assert r.status_code == 422


# --- Session --------------------------------------------------------------------------


def test_no_session_is_401(db, texts, client):
    r = client.get("/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_dev_header_ignored_unless_enabled(db, texts, client):
    assert client.get("/me", headers={"X-Person-Id": "cg"}).status_code == 401


def test_logout_ends_the_session(db, texts, client):
    client.post("/auth/login", json={"phone": KNOWN})
    client.post("/auth/verify", json={"phone": KNOWN, "code": code_in(texts[0][1])})
    assert client.get("/me").status_code == 200
    stolen = client.cookies.get(SESSION_COOKIE)
    assert client.post("/auth/logout").status_code == 200
    # The server-side row is gone, so even a copied cookie no longer works.
    client.cookies.set(SESSION_COOKIE, stolen)
    assert client.get("/me").status_code == 401


def test_expired_session_is_401(db, texts, client):
    from app.models import AuthSession

    client.post("/auth/login", json={"phone": KNOWN})
    client.post("/auth/verify", json={"phone": KNOWN, "code": code_in(texts[0][1])})
    session = db.scalar(select(AuthSession))
    session.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.get("/me").status_code == 401


# --- Twilio sender ----------------------------------------------------------------------


@pytest.fixture
def twilio_env(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550000000")
    monkeypatch.delenv("TWILIO_MESSAGING_SERVICE_SID", raising=False)


def test_send_sms_posts_to_twilio(twilio_env):
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["form"] = dict(httpx.QueryParams(request.content.decode()))
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(201, json={"sid": "SM1"})

    result = sms.send_sms(KNOWN, "hola", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert result.ok
    assert seen["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC_test/Messages.json"
    assert seen["form"] == {"To": KNOWN, "From": "+15550000000", "Body": "hola"}
    assert seen["auth"].startswith("Basic ")


def test_send_sms_reports_twilio_error(twilio_env):
    def handler(request):
        return httpx.Response(400, json={"code": 21608, "message": "unverified number"})

    result = sms.send_sms(KNOWN, "hola", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert not result.ok and result.code == sms.TRIAL_UNVERIFIED


def test_send_sms_network_error(twilio_env):
    def handler(request):
        raise httpx.ConnectError("boom")

    result = sms.send_sms(KNOWN, "hola", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert not result.ok and "Error de red" in result.error


def test_send_sms_not_configured(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    assert not sms.send_sms(KNOWN, "hola").ok
