"""SMS through Twilio Programmable Messaging. Only used for the 6-digit login code.

The bot, invites and emergency notifications stay on WhatsApp (whatsapp.py). The
code is generated, hashed and checked by us (api/auth.py); Twilio only delivers text.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from app.whatsapp import mask

log = logging.getLogger(__name__)

TWILIO_API = "https://api.twilio.com/2010-04-01"

# Twilio error: a trial account can only text numbers verified in its console.
TRIAL_UNVERIFIED = 21608


@dataclass
class SmsResult:
    ok: bool
    code: int | None = None
    error: str | None = None


def configured() -> bool:
    return bool(
        os.environ.get("TWILIO_ACCOUNT_SID")
        and os.environ.get("TWILIO_AUTH_TOKEN")
        and (os.environ.get("TWILIO_FROM_NUMBER") or os.environ.get("TWILIO_MESSAGING_SERVICE_SID"))
    )


def send_sms(to: str, body: str, client: httpx.Client | None = None) -> SmsResult:
    """Sends one SMS. Never raises; failures come back in the result and the log
    (with the number masked, never the body: it carries the login code)."""
    if not configured():
        log.error("Cannot text %s: TWILIO_* settings are missing", mask(to))
        return SmsResult(False, None, "SMS no está configurado (faltan credenciales de Twilio).")
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    form = {"To": to, "Body": body}
    if os.environ.get("TWILIO_MESSAGING_SERVICE_SID"):
        form["MessagingServiceSid"] = os.environ["TWILIO_MESSAGING_SERVICE_SID"]
    else:
        form["From"] = os.environ["TWILIO_FROM_NUMBER"]
    owns_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        response = client.post(
            f"{TWILIO_API}/Accounts/{sid}/Messages.json",
            data=form,
            auth=(sid, os.environ["TWILIO_AUTH_TOKEN"]),
        )
        if response.status_code in (200, 201):
            return SmsResult(True)
        try:
            err = response.json()
        except ValueError:
            err = {}
        code = err.get("code")
        message = err.get("message") or f"HTTP {response.status_code}"
        log.error("SMS to %s failed: %s %s", mask(to), response.status_code, message[:300])
        return SmsResult(False, code, message)
    except httpx.HTTPError as exc:
        log.error("SMS to %s failed: %s", mask(to), exc)
        return SmsResult(False, None, f"Error de red: {exc.__class__.__name__}")
    finally:
        if owns_client:
            client.close()
