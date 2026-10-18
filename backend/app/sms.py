"""SMS through Twilio Programmable Messaging. Only used for the 6-digit login code.

Invites are matched on the phone in the app and emergency notifications go to the web
inbox (notify.py). The code is generated, hashed and checked by us (api/auth.py); Twilio only delivers text.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

import httpx


log = logging.getLogger(__name__)

def mask(phone: str) -> str:
    """Phone numbers are personal data: logs only keep the last 4 digits."""
    return "***" + phone[-4:] if phone else "***"


TWILIO_API = "https://api.twilio.com/2010-04-01"

# Twilio error: a trial account can only text numbers verified in its console.
TRIAL_UNVERIFIED = 21608
TRIAL_TEMPLATE_TTL_MINUTES = 5  # what the sms_2fa template's text promises


@dataclass
class SmsResult:
    ok: bool
    code: int | None = None  # Twilio error code
    error: str | None = None
    body: str | None = None  # the text Twilio says it sent


def trial_template() -> str | None:
    """SIMULATED security, demo only. A Twilio trial account (One Console) rejects free
    text ("Trial accounts can only use predefined SMS templates"). Its `sms_2fa`
    template writes a verification code into the text itself and echoes the text
    back, so auth reads the code from the response. On a trial that code is the
    SAME every time, so anyone who knows it can log in as any registered phone:
    use only with fictional data, like ALLOW_DEV_IDENTITY_HEADER. Unset in any
    real deploy (an upgraded account sends our own random code)."""
    return os.environ.get("TWILIO_TRIAL_TEMPLATE") or None


def code_in(text: str | None) -> str | None:
    match = re.search(r"\b(\d{6})\b", text or "")
    return match.group(1) if match else None


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
            try:
                body = response.json().get("body")
            except ValueError:
                body = None
            return SmsResult(True, body=body)
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
