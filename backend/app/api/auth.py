"""Sign-up / login with a 6-digit code sent by SMS (docs/contract.md "Auth").

POST /auth/signup, /auth/login -> code_sent; POST /auth/verify -> session cookie;
POST /auth/logout. No passwords. The phone number is the identity; email is
unverified contact info and never grants access.

Anti-enumeration: nothing here reveals whether a phone has an account. Login for
an unknown phone stores a code row (so rate limits behave the same) but sends
nothing; sign-up for a known phone sends a normal login code.
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

from app import sms
from app.deps import SESSION_COOKIE, get_db, hash_token
from app.errors import api_error
from app.models import (
    AuthSession,
    Invite,
    InviteStatus,
    LoginCode,
    Patient,
    PatientAccess,
    Person,
    utcnow,
)
from app.whatsapp import mask

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


def _issue_code(db: Session, phone: str, send: bool, signup_name: str | None = None,
                signup_email: str | None = None) -> sms.SmsResult | None:
    """Sends (when `send`) and stores a fresh code for the phone, retiring any earlier
    unused one. Returns the delivery result, or None when nothing was sent."""
    code, result = None, None
    if send and sms.trial_template():
        # SIMULATED: a Twilio trial only sends predefined templates; the template writes
        # its own code into the text, which Twilio echoes back. See sms.trial_template.
        result = sms.send_sms(phone, sms.trial_template())
        code = sms.code_in(result.body) if result.ok else None
        if result.ok and code is None:
            result = sms.SmsResult(False, None, "La plantilla de Twilio no devolvió un código.")
    elif send:
        code = f"{secrets.randbelow(1_000_000):06d}"
        result = _deliver(phone, code)
    code = code or f"{secrets.randbelow(1_000_000):06d}"  # unsent: nobody can know it

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


@router.post("/auth/signup")
def signup(body: SignupIn, db: Session = Depends(get_db)) -> dict:
    """New phone: the code carries name/email; the person is created on verify.
    Known phone: a normal login code (the stored name is kept)."""
    phone = normalize_phone(body.phone)
    _check_rate_limit(db, phone)
    known = db.scalar(select(Person.id).where(Person.phone == phone)) is not None
    if known:
        result = _issue_code(db, phone, send=True)
    else:
        result = _issue_code(db, phone, send=True, signup_name=body.name, signup_email=body.email or None)
    # Both branches text the phone, so reporting a failed SMS reveals nothing.
    if not result.ok:
        raise api_error(502, "sms_unreachable",
                        "No pudimos mandar el SMS a ese número. Revisalo y probá de nuevo en un minuto.")
    return _code_sent(phone)


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    """Always the same `code_sent` body. Unknown phones get a code row (never sent)
    so the rate limit answers the same way; SMS failures are only logged, because
    an error here would only ever happen for registered phones."""
    phone = normalize_phone(body.phone)
    _check_rate_limit(db, phone)
    known = db.scalar(select(Person.id).where(Person.phone == phone)) is not None
    result = _issue_code(db, phone, send=known)
    if result is not None and not result.ok:
        log.error("Login code to %s not delivered: %s", mask(phone), result.error)
    return _code_sent(phone)


# --- Verifying ------------------------------------------------------------------------


def _accept_invites(db: Session, person: Person) -> None:
    """Pending invites for this (just proven) phone become memberships."""
    invites = db.scalars(select(Invite).where(Invite.phone == person.phone,
                                              Invite.status == InviteStatus.pending))
    for invite in invites:
        exists = db.scalar(select(PatientAccess.id).where(PatientAccess.person_id == person.id,
                                                          PatientAccess.patient_id == invite.patient_id))
        if exists is None:
            db.add(PatientAccess(person_id=person.id, patient_id=invite.patient_id, role=invite.role))
        invite.status = InviteStatus.accepted
        invite.accepted_at = utcnow()


def _cookie_attrs() -> dict:
    """SameSite=None by default: the web and the API live on different sites
    (onrender.com is a public suffix), so a Lax cookie would never reach the API.
    Browsers drop SameSite=None cookies that are not Secure; local http dev sets
    SESSION_COOKIE_SECURE=0 with SESSION_COOKIE_SAMESITE=lax (localhost is one site)."""
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
        if not row.signup_name:  # login code for an unknown phone: it was never sent
            raise invalid
        person = Person(phone=phone, display_name=row.signup_name, email=row.signup_email)
        db.add(person)
        db.flush()
    row.used_at = utcnow()
    _accept_invites(db, person)
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
        "user": {"id": person.id, "name": person.display_name},
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
