"""WhatsApp channel through the Meta Cloud API: receive, download audio, reply.

Flow per incoming message (runs in the background, after the webhook acked):
sender phone -> caregiver -> patient (asks "which patient?" if several) ->
download + transcribe with that patient's vocabulary -> process_report ->
reply with confirmation_text. Any failure becomes a clear WhatsApp message.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time
import unicodedata
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ingest
from app.models import ROLE_PERMISSIONS, Patient, PatientAccess, Permission, Person, SessionLocal
from app.transcribe import Transcript, TranscriptionError, transcribe

log = logging.getLogger(__name__)

DEFAULT_GRAPH_VERSION = "v23.0"

# Graph API error code when the recipient is not in the test number's allowed list.
RECIPIENT_NOT_ALLOWED = 131030

MSG_UNSUPPORTED = "Por ahora solo puedo registrar notas de voz o texto. Enviá el reporte del turno como nota de voz."
MSG_DOWNLOAD_FAILED = "No pude descargar tu nota de voz. ¿Podés enviarla de nuevo?"
MSG_UNKNOWN_NUMBER = (
    "Este número no está registrado en CercanIA. Pedile a la persona responsable del paciente que te invite."
)
MSG_NO_PATIENTS = "No tenés pacientes asignados para enviar reportes. Pedile a la persona responsable que te invite."
MSG_PROCESSING_UNAVAILABLE = (
    "Recibí tu mensaje, pero todavía no puedo analizar reportes, así que no quedó registrado. "
    "Probá de nuevo más tarde."
)
MSG_UNEXPECTED = "Hubo un error inesperado al procesar tu reporte. ¿Podés enviarlo de nuevo?"
MSG_QUEUED = "Guardé este reporte también. Primero decime de qué paciente es el anterior."
MSG_NEXT_PENDING = "Tenés otro reporte esperando."
MSG_EXPIRED = (
    "{count} reporte(s) que enviaste quedaron sin registrar porque no elegiste el paciente a tiempo. "
    "Por favor, volvé a enviarlos."
)
# Fixed text (AGENTS.md section 7): added by code whenever red_flag is true. red_flag itself
# comes from the model in triage.py; this wording never does.
MSG_RED_FLAG = "⚠️ Si es una emergencia, llamá a emergencias o al médico ahora."


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

# Overridden in tests.
session_factory = SessionLocal

REPORTING_ROLES = [role for role, perms in ROLE_PERMISSIONS.items() if Permission.send_report in perms]


@dataclass
class PendingChoice:
    """A report waiting for the caregiver to say which patient it is about."""

    message: IncomingMessage
    patients: list[tuple[str, str]]  # (patient_id, display_name)
    created: float


class PendingChoices:
    """Reports waiting for "which patient?", queued per sender in arrival order.

    In memory: enough for a single instance. Nothing is dropped silently: a new
    report is queued behind the current one, and reports that expire are
    counted so the caregiver is told to resend them.
    """

    def __init__(self, ttl_seconds: int = 30 * 60):
        self.ttl = ttl_seconds
        self._queues: dict[str, list[PendingChoice]] = {}
        self._lock = threading.Lock()

    def put(self, sender: str, choice: PendingChoice) -> None:
        with self._lock:
            self._queues.setdefault(sender, []).append(choice)

    def first(self, sender: str) -> PendingChoice | None:
        with self._lock:
            queue = self._queues.get(sender)
            return queue[0] if queue else None

    def pop_first(self, sender: str) -> None:
        with self._lock:
            queue = self._queues.get(sender)
            if queue:
                queue.pop(0)
            if not queue:
                self._queues.pop(sender, None)

    def take_expired(self, sender: str) -> int:
        """Removes expired reports for this sender and returns how many there were."""
        now = time.monotonic()
        with self._lock:
            queue = self._queues.get(sender, [])
            alive = [c for c in queue if now - c.created <= self.ttl]
            if alive:
                self._queues[sender] = alive
            else:
                self._queues.pop(sender, None)
            return len(queue) - len(alive)


pending_choices = PendingChoices()


def caregiver_for(session: Session, wa_id: str) -> Person | None:
    """WhatsApp sends digits only; person.phone is E.164 ("+59899...")."""
    phones = ["+" + candidate for candidate in _recipient_candidates(wa_id)]
    return session.scalars(select(Person).where(Person.phone.in_(phones))).first()


def reportable_patients(session: Session, person_id: str) -> list[tuple[str, str]]:
    rows = session.execute(
        select(Patient.id, Patient.display_name)
        .join(PatientAccess, PatientAccess.patient_id == Patient.id)
        .where(PatientAccess.person_id == person_id, PatientAccess.role.in_(REPORTING_ROLES))
        .order_by(Patient.display_name)
    )
    return [(row.id, row.display_name) for row in rows]


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


def pick_patient(answer: str | None, patients: list[tuple[str, str]]) -> tuple[str, str] | None:
    """Accepts the list number ("2") or part of the name ("jorge")."""
    answer = _normalize(answer or "").strip(" .")
    if not answer:
        return None
    if answer.isdigit():
        index = int(answer) - 1
        return patients[index] if 0 <= index < len(patients) else None
    matches = [p for p in patients if answer in _normalize(p[1])]
    return matches[0] if len(matches) == 1 else None


def which_patient_question(patients: list[tuple[str, str]]) -> str:
    options = "\n".join(f"{i}. {name}" for i, (_, name) in enumerate(patients, start=1))
    return f"¿De qué paciente es el reporte? Respondé con el número o el nombre:\n{options}"


def reply_for(result: dict) -> str:
    """Text for the caregiver from a ProcessResult. The wording comes from
    process_report; only the red-flag line is added here, by fixed rule."""
    text = result.get("confirmation_text") or result.get("message")
    if not text:
        text = "Registré tu reporte." if result.get("status") == "ok" else MSG_UNEXPECTED
    if result.get("red_flag"):
        text = f"{MSG_RED_FLAG}\n\n{text}"
    return text


def handle_message(message: IncomingMessage) -> None:
    """Background job for one incoming message. Never raises."""
    try:
        with session_factory() as db:
            person = caregiver_for(db, message.sender)
            if person is None:
                send_text(message.sender, MSG_UNKNOWN_NUMBER)
                return

            expired = pending_choices.take_expired(message.sender)
            if expired:
                send_text(message.sender, MSG_EXPIRED.format(count=expired))

            pending = pending_choices.first(message.sender)
            if pending and message.type == "text":
                patient = pick_patient(message.text, pending.patients)
                if patient is not None:
                    pending_choices.pop_first(message.sender)
                    process(db, pending.message, person.id, patient)
                    following = pending_choices.first(message.sender)
                    if following:
                        send_text(message.sender, f"{MSG_NEXT_PENDING} {which_patient_question(following.patients)}")
                    return
                if not _looks_like_report(message.text):
                    send_text(message.sender, which_patient_question(pending.patients))
                    return
                # A typed report while a choice is pending: queue it, don't drop it.

            if not _is_report(message):
                send_text(message.sender, MSG_UNSUPPORTED)
                return
            patients = reportable_patients(db, person.id)
            if not patients:
                send_text(message.sender, MSG_NO_PATIENTS)
                return
            if len(patients) == 1 and pending is None:
                process(db, message, person.id, patients[0])
                return
            pending_choices.put(message.sender, PendingChoice(message, patients, time.monotonic()))
            if pending is None:
                send_text(message.sender, which_patient_question(patients))
            else:
                send_text(message.sender, f"{MSG_QUEUED}\n\n{which_patient_question(pending.patients)}")
    except Exception:
        log.exception("Unexpected error processing %s", message.id)
        send_text(message.sender, MSG_UNEXPECTED)


def process(db: Session, report: IncomingMessage, caregiver_id: str, patient: tuple[str, str]) -> None:
    transcript = to_transcript(report, ingest.vocabulary_for(db, patient[0]))
    if transcript is not None:
        deliver(report, caregiver_id, patient[0], transcript)


def _looks_like_report(text: str | None) -> bool:
    """An answer to "which patient?" is a number or a name; a report is a sentence."""
    return len((text or "").split()) >= 4


def _is_report(message: IncomingMessage) -> bool:
    if message.type == "audio":
        return bool(message.audio_id)
    return message.type == "text" and bool(message.text and message.text.strip())


def to_transcript(message: IncomingMessage, vocabulary: list[str]) -> Transcript | None:
    """Voice note -> transcript; typed report -> transcript as is. On failure the
    caregiver is told why and None is returned."""
    if message.type == "text":
        return Transcript(text=message.text.strip())
    try:
        audio, mime = download_media(message.audio_id)
    except DownloadError as exc:
        log.error("Download failed for %s: %s", message.id, exc)
        send_text(message.sender, MSG_DOWNLOAD_FAILED)
        return None
    try:
        return transcribe(audio, mime_type=mime.split(";")[0].strip(), vocabulary=vocabulary)
    except TranscriptionError as exc:
        log.error("Transcription failed for %s: %s", message.id, exc)
        send_text(message.sender, exc.user_message)
        return None


def deliver(message: IncomingMessage, caregiver_id: str, patient_id: str, transcript: Transcript) -> None:
    """process_report, then the confirmation back to the caregiver.

    The transcript is health data: it goes to the database, never to the logs.
    """
    log.info(
        "Processing message %s from %s for %s (%s, %d chars)",
        message.id, mask(message.sender), patient_id, message.type, len(transcript.text),
    )
    try:
        result = ingest.process_report(
            patient_id=patient_id,
            sender_id=caregiver_id,
            transcript=transcript.text,
            audio_ref=None,
            message_id=message.id,
        )
    except ingest.ProcessingUnavailable:
        log.error("Message %s: process_report is not available yet", message.id)
        send_text(message.sender, MSG_PROCESSING_UNAVAILABLE)
        return
    send_text(message.sender, reply_for(result))
