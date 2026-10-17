"""WhatsApp channel through the Meta Cloud API: receive, download audio, reply.

Flow per incoming message (runs in the background, after the webhook acked):
voice note -> download from the Graph API -> transcribe -> handle_transcript.
Any failure is turned into a clear WhatsApp message to the caregiver.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time
from dataclasses import dataclass

import httpx

from app.transcribe import Transcript, TranscriptionError, transcribe

log = logging.getLogger(__name__)

DEFAULT_GRAPH_VERSION = "v23.0"

# Graph API error code when the recipient is not in the test number's allowed list.
RECIPIENT_NOT_ALLOWED = 131030

MSG_UNSUPPORTED = "Por ahora solo puedo registrar notas de voz o texto. Enviá el reporte del turno como nota de voz."
MSG_DOWNLOAD_FAILED = "No pude descargar tu nota de voz. ¿Podés enviarla de nuevo?"


def mask(phone: str) -> str:
    """Phone numbers are personal data: logs only keep the last 4 digits."""
    return "***" + phone[-4:] if phone else "***"


def graph_url(path: str) -> str:
    version = os.environ.get("WHATSAPP_GRAPH_VERSION", DEFAULT_GRAPH_VERSION)
    return f"https://graph.facebook.com/{version}/{path.lstrip('/')}"


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}"}


# --- Webhook verification -------------------------------------------------------


def verify_subscription(mode: str | None, token: str | None, challenge: str | None) -> str | None:
    """Meta's GET handshake. Returns the challenge to echo back, or None to reject."""
    expected = os.environ.get("WHATSAPP_VERIFY_TOKEN")
    if mode == "subscribe" and expected and token and hmac.compare_digest(token, expected) and challenge:
        return challenge
    return None


def valid_signature(body: bytes, header: str | None) -> bool:
    """Checks X-Hub-Signature-256 (HMAC-SHA256 of the raw body with the app secret)."""
    secret = os.environ.get("WHATSAPP_APP_SECRET")
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), expected)


# --- Incoming messages ----------------------------------------------------------


@dataclass
class IncomingMessage:
    id: str
    sender: str  # wa_id, digits only, e.g. "5491122334455"
    type: str  # "audio", "text", "image", ...
    audio_id: str | None = None
    audio_mime: str | None = None
    text: str | None = None


def parse_messages(payload: dict) -> list[IncomingMessage]:
    """Extracts user messages from a webhook payload. Status updates are ignored."""
    messages = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            for raw in (change.get("value") or {}).get("messages") or []:
                if not raw.get("id") or not raw.get("from"):
                    log.warning("Skipping malformed WhatsApp message with keys %s", sorted(raw))
                    continue
                audio = raw.get("audio") or {}
                messages.append(
                    IncomingMessage(
                        id=raw["id"],
                        sender=raw["from"],
                        type=raw.get("type", "unknown"),
                        audio_id=audio.get("id"),
                        audio_mime=audio.get("mime_type"),
                        text=(raw.get("text") or {}).get("body"),
                    )
                )
    return messages


class SeenMessages:
    """Remembers processed message ids so Meta's retries are not processed twice.

    In memory: enough for a single instance. process_report is also idempotent
    on message_id at the database level, so a restart cannot create duplicates.
    """

    def __init__(self, ttl_seconds: int = 24 * 3600):
        self.ttl = ttl_seconds
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def first_time(self, message_id: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._seen = {k: t for k, t in self._seen.items() if now - t < self.ttl}
            if message_id in self._seen:
                return False
            self._seen[message_id] = now
            return True


seen_messages = SeenMessages()


# --- Graph API calls ------------------------------------------------------------


class DownloadError(Exception):
    pass


def download_media(media_id: str, client: httpx.Client | None = None) -> tuple[bytes, str]:
    """Media id -> temporary URL -> bytes. Both calls need the bearer token."""
    owns_client = client is None
    client = client or httpx.Client(timeout=30)
    try:
        meta = client.get(graph_url(media_id), headers=_auth_headers())
        if meta.status_code != 200:
            raise DownloadError(f"media lookup {meta.status_code}: {meta.text[:300]}")
        info = meta.json()
        media = client.get(info["url"], headers=_auth_headers(), follow_redirects=True)
        if media.status_code != 200:
            raise DownloadError(f"media download {media.status_code}")
        return media.content, info.get("mime_type", "audio/ogg")
    except httpx.HTTPError as exc:
        raise DownloadError(str(exc)) from exc
    finally:
        if owns_client:
            client.close()


def send_text(to: str, text: str, client: httpx.Client | None = None) -> bool:
    """Sends a text reply. Returns False (and logs) instead of raising."""
    if not os.environ.get("WHATSAPP_TOKEN") or not os.environ.get("WHATSAPP_PHONE_NUMBER_ID"):
        log.error("Cannot reply to %s: WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID is not set", mask(to))
        return False
    owns_client = client is None
    client = client or httpx.Client(timeout=15)
    url = graph_url(f"{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages")
    try:
        for recipient in _recipient_candidates(to):
            response = client.post(
                url,
                headers=_auth_headers(),
                json={
                    "messaging_product": "whatsapp",
                    "to": recipient,
                    "type": "text",
                    "text": {"body": text},
                },
            )
            if response.status_code == 200:
                return True
            try:
                code = (response.json().get("error") or {}).get("code")
            except ValueError:  # HTML or empty error body (proxy 5xx, Meta error page)
                code = None
            if code != RECIPIENT_NOT_ALLOWED:
                break
        log.error("WhatsApp send to %s failed: %s %s", mask(to), response.status_code, response.text[:300])
        return False
    except httpx.HTTPError as exc:
        log.error("WhatsApp send to %s failed: %s", mask(to), exc)
        return False
    finally:
        if owns_client:
            client.close()


def _recipient_candidates(wa_id: str) -> list[str]:
    """Argentina (549...) and Mexico (521...) senders arrive with an extra mobile
    digit that the test number's allowed list may store without. Try both."""
    candidates = [wa_id]
    if wa_id.startswith("549"):
        candidates.append("54" + wa_id[3:])
    elif wa_id.startswith("521"):
        candidates.append("52" + wa_id[3:])
    return candidates


# --- Processing -----------------------------------------------------------------


def handle_message(message: IncomingMessage) -> None:
    """Background job for one incoming message. Never raises."""
    try:
        if message.type == "audio" and message.audio_id:
            try:
                audio, mime = download_media(message.audio_id)
            except DownloadError as exc:
                log.error("Download failed for %s: %s", message.id, exc)
                send_text(message.sender, MSG_DOWNLOAD_FAILED)
                return
            try:
                transcript = transcribe(audio, mime_type=mime.split(";")[0].strip())
            except TranscriptionError as exc:
                log.error("Transcription failed for %s: %s", message.id, exc)
                send_text(message.sender, exc.user_message)
                return
        elif message.type == "text" and message.text and message.text.strip():
            # Text fallback: a typed report is processed like a transcript.
            transcript = Transcript(text=message.text.strip())
        else:
            send_text(message.sender, MSG_UNSUPPORTED)
            return
        handle_transcript(message, transcript)
    except Exception:
        log.exception("Unexpected error processing %s", message.id)
        send_text(message.sender, "Hubo un error inesperado al procesar tu reporte. ¿Podés enviarlo de nuevo?")


def handle_transcript(message: IncomingMessage, transcript: Transcript) -> None:
    """Hand-off point to the brain. CIA-19/CIA-20 replace the log with
    process_report() and the confirmation reply.

    The transcript is health data: it goes to the database, never to the logs.
    """
    log.info(
        "Transcript ready for message %s from %s (%s, %d chars, %d segments)",
        message.id,
        mask(message.sender),
        message.type,
        len(transcript.text),
        len(transcript.segments),
    )
