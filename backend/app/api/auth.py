"""Sign-up / login with a 6-digit code sent by SMS (docs/contract.md "Auth").

POST /auth/login (or /auth/signup) -> code_sent; POST /auth/verify -> session cookie,
or `profile_required` for a new phone; POST /auth/logout. No passwords. The phone
number is the identity; email is unverified contact info and never grants access.

Anti-enumeration: before the code is verified nothing reveals whether a phone has an
account. Every phone gets the same SMS and the same answer; only someone holding the
code learns that the phone is new, and is then asked for a name (one flow for
sign-up and login).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from typing_extensions import Annotated

from app import roles, sms
from app.deps import SESSION_COOKIE, get_db, hash_token
from app.errors import api_error
from app.models import (
    AuthSession,
    LoginCode,
    Patient,
    PatientAccess,
    Person,
    utcnow,
)
from app.sms import mask

log = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

MAX_ATTEMPTS = 5  # wrong codes before the code locks
RESEND_AFTER_SEC = 60  # one new code per phone per minute
MAX_CODES_PER_HOUR = 5  # per phone
_PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")

MSG_SMS = "Tu código de CercanIA es {code}. Vence en {minutes} minutos. No lo compartas con nadie."


def code_ttl_minutes() -> int:
    ttl = int(os.environ.get("LOGIN_CODE_TTL_MINUTES") or 10)
    # The trial template's text says the code expires in 5 minutes; never promise more.
    return min(ttl, sms.TRIAL_TEMPLATE_TTL_MINUTES) if sms.trial_template() else ttl


def session_ttl() -> timedelta:
    return timedelta(days=int(os.environ.get("SESSION_TTL_DAYS") or 30))


def normalize_phone(raw: str) -> str:
    """E.164 or `phone_invalid`. Spaces, dashes, dots and parentheses are ignored."""
    phone = re.sub(r"[\s\-().]", "", raw or "")
    if not _PHONE_RE.match(phone):
        raise api_error(400, "phone_invalid", "Revisá el número: tiene que incluir el código de país, por ejemplo +598 99 123 456.")
    return phone


def _hash_code(salt: str, phone: str, code: str) -> str:
    return hmac.new(salt.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive UTC


# --- Request bodies -------------------------------------------------------------

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=254)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{6}$")]


class SignupIn(BaseModel):
    name: Name
    email: Email | None = None
    phone: str


class LoginIn(BaseModel):
    phone: str


class VerifyIn(BaseModel):
    phone: str
    code: Code
    # Only used when the phone has no account yet (the `profile_required` step).
    name: Name | None = None
    email: Email | None = None


# --- Sending a code ---------------------------------------------------------------


def _check_rate_limit(db: Session, phone: str) -> None:
    now = utcnow()
    last = db.scalar(select(func.max(LoginCode.created_at)).where(LoginCode.phone == phone))
    if last is not None and now - _aware(last) < timedelta(seconds=RESEND_AFTER_SEC):
        raise api_error(429, "too_many_requests", "Esperá un minuto antes de pedir otro código.")
    recent = db.scalar(
        select(func.count()).select_from(LoginCode)
        .where(LoginCode.phone == phone, LoginCode.created_at >= now - timedelta(hours=1))
    )
    if recent >= MAX_CODES_PER_HOUR:
        raise api_error(429, "too_many_requests", "Pediste demasiados códigos. Probá de nuevo en una hora.")


def _issue_code(db: Session, phone: str, signup_name: str | None = None,
                signup_email: str | None = None) -> sms.SmsResult:
    """Sends and stores a fresh code for the phone, retiring any earlier unused one.
    Returns the delivery result."""
    if sms.trial_template():
        # SIMULATED: a Twilio trial only sends predefined templates; the template writes
        # its own code into the text, which Twilio echoes back. See sms.trial_template.
        result = sms.send_sms(phone, sms.trial_template())
        code = sms.code_in(result.body) if result.ok else None
        if result.ok and code is None:
            result = sms.SmsResult(False, None, "La plantilla de Twilio no devolvió un código.")
    else:
        code = f"{secrets.randbelow(1_000_000):06d}"
        result = _deliver(phone, code)
    code = code or f"{secrets.randbelow(1_000_000):06d}"  # failed send: nobody can know it

    db.execute(update(LoginCode).where(LoginCode.phone == phone, LoginCode.used_at.is_(None))
               .values(used_at=utcnow()))
    salt = secrets.token_hex(16)
    db.add(LoginCode(phone=phone, code_hash=_hash_code(salt, phone, code), salt=salt,
                     signup_name=signup_name, signup_email=signup_email,
                     expires_at=utcnow() + timedelta(minutes=code_ttl_minutes())))
    db.commit()
    return result


def _deliver(phone: str, code: str) -> sms.SmsResult:
    if os.environ.get("AUTH_DEV_LOG_CODES") == "1":
        # SIMULATED delivery for local dev without Twilio. Never set in a real deploy.
        log.warning("AUTH_DEV_LOG_CODES: login code for %s is %s", mask(phone), code)
        return sms.SmsResult(True)
    return sms.send_sms(phone, MSG_SMS.format(code=code, minutes=code_ttl_minutes()))


def _code_sent(phone: str) -> dict:
    return {"status": "code_sent", "phone_last4": phone[-4:],
            "expires_in_sec": code_ttl_minutes() * 60, "resend_after_sec": RESEND_AFTER_SEC}


def _send_code(db: Session, phone: str, signup_name: str | None = None,
               signup_email: str | None = None) -> dict:
    _check_rate_limit(db, phone)
    known = db.scalar(select(Person.id).where(Person.phone == phone)) is not None
    if known:  # a known phone keeps its stored name
        signup_name = signup_email = None
    result = _issue_code(db, phone, signup_name=signup_name, signup_email=signup_email)
    # Every phone is texted, so reporting a failed SMS reveals nothing.
    if not result.ok:
        log.error("Login code to %s not delivered: %s", mask(phone), result.error)
        raise api_error(502, "sms_unreachable",
                        "No pudimos mandar el SMS a ese número. Revisalo y probá de nuevo en un minuto.")
    return _code_sent(phone)


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    """Any phone, registered or not, gets a code. The web uses only this one: a new
    phone gives its name after the code (`profile_required` in /auth/verify)."""
    return _send_code(db, normalize_phone(body.phone))


@router.post("/auth/signup")
def signup(body: SignupIn, db: Session = Depends(get_db)) -> dict:
    """Like login, with the name and email up front for a new phone (then verify
    creates the person directly). A known phone keeps its stored name."""
    return _send_code(db, normalize_phone(body.phone), body.name, body.email or None)


# --- Verifying ------------------------------------------------------------------------


def _cookie_attrs() -> dict:
    """The web reaches the API through its same-origin /api rewrite, so the cookie is
    first-party there and the deploy sets SESSION_COOKIE_SAMESITE=lax. The SameSite=None
    default only matters for a browser calling the API host directly. Local http dev
    also sets SESSION_COOKIE_SECURE=0."""
    return {"httponly": True, "path": "/",
            "secure": os.environ.get("SESSION_COOKIE_SECURE", "1") != "0",
            "samesite": (os.environ.get("SESSION_COOKIE_SAMESITE") or "none").lower()}


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, max_age=int(session_ttl().total_seconds()), **_cookie_attrs())


@router.post("/auth/verify")
def verify(body: VerifyIn, response: Response, db: Session = Depends(get_db)) -> dict:
    phone = normalize_phone(body.phone)
    row = db.scalars(select(LoginCode).where(LoginCode.phone == phone, LoginCode.used_at.is_(None))
                     .order_by(LoginCode.id.desc()).limit(1)).first()
    invalid = api_error(400, "code_invalid", "El código no es correcto. Revisalo y probá de nuevo.")
    if row is None:
        raise invalid
    if row.attempts >= MAX_ATTEMPTS:
        raise api_error(429, "too_many_attempts", "Demasiados intentos. Pedí un código nuevo.")
    if _aware(row.expires_at) <= utcnow():
        raise api_error(400, "code_expired", "El código venció. Pedí uno nuevo.")
    if not hmac.compare_digest(row.code_hash, _hash_code(row.salt, phone, body.code)):
        row.attempts += 1
        db.commit()
        if row.attempts >= MAX_ATTEMPTS:
            raise api_error(429, "too_many_attempts", "Demasiados intentos. Pedí un código nuevo.")
        raise invalid

    person = db.scalar(select(Person).where(Person.phone == phone))
    if person is None:
        name = body.name or row.signup_name
        if not name:
            # New phone, and the code proved the caller holds it: ask for the name. The code
            # stays valid (same expiry, same attempts) so the next call can send it again.
            return {"status": "profile_required"}
        email = (body.email or None) if body.name else row.signup_email
        person = Person(phone=phone, display_name=name, email=email)
        db.add(person)
        db.flush()
        # Starting role (CIA-48): admin pre-registration, else a pending invite, else patient.
        roles.on_signup(db, person)
    else:
        # An existing account left with no role at all is a patient too.
        roles.ensure_default_role(db, person)
    row.used_at = utcnow()
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=hash_token(token), person_id=person.id,
                       expires_at=utcnow() + session_ttl()))
    db.commit()
    _set_session_cookie(response, token)

    memberships = db.execute(
        select(PatientAccess, Patient).join(Patient, PatientAccess.patient_id == Patient.id)
        .where(PatientAccess.person_id == person.id).order_by(Patient.display_name, Patient.id)
    )
    return {
        "status": "signed_in",
        "user": {"id": person.id, "name": person.display_name},
        "is_admin": roles.is_admin(person),
        "memberships": [{"patient_id": p.id, "display_name": p.display_name, "role": a.role.value}
                        for a, p in memberships],
    }


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.get(AuthSession, hash_token(token))
        if session is not None:
            db.delete(session)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, **_cookie_attrs())
    return {"status": "logged_out"}
