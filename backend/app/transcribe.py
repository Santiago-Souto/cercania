"""Audio -> text with Groq's Whisper API and a vocabulary hint.

The hint is passed as Whisper's `prompt`, which biases spelling towards the
words we expect (care terms, medication names) without changing what was said.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "whisper-large-v3-turbo"

# Generic care vocabulary in Spanish. Patient-specific terms (medication names
# from the care plan) are appended by the caller once the patient is known.
BASE_VOCABULARY = [
    "cuidadora",
    "turno",
    "medicación",
    "pastilla",
    "comprimido",
    "dosis",
    "diuresis",
    "orinó",
    "pañal",
    "deposición",
    "apetito",
    "durmió",
    "ánimo",
    "dolor",
    "caída",
    "andador",
    "silla de ruedas",
    "presión",
    "glucemia",
]

# Whisper only reads the last ~224 tokens of the prompt; keep it short.
MAX_PROMPT_CHARS = 600


class TranscriptionError(Exception):
    """Transcription failed; `user_message` is safe to send to the caregiver."""

    def __init__(self, detail: str, user_message: str):
        super().__init__(detail)
        self.user_message = user_message


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    text: str
    language: str | None = None
    duration: float | None = None
    segments: list[Segment] = field(default_factory=list)


def build_prompt(vocabulary: list[str] | None) -> str:
    words = list(dict.fromkeys(BASE_VOCABULARY + (vocabulary or [])))
    prompt = "Reporte de fin de turno de una cuidadora: " + ", ".join(words) + "."
    return prompt[-MAX_PROMPT_CHARS:]


def transcribe(
    audio: bytes,
    filename: str = "voice.ogg",
    mime_type: str = "audio/ogg",
    vocabulary: list[str] | None = None,
    client: httpx.Client | None = None,
) -> Transcript:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise TranscriptionError(
            "GROQ_API_KEY is not set",
            "No pude transcribir el audio por un problema de configuración. Ya avisamos al equipo.",
        )
    if not audio:
        raise TranscriptionError("empty audio", "El audio llegó vacío. ¿Podés enviarlo de nuevo?")

    data = {
        "model": os.environ.get("GROQ_TRANSCRIPTION_MODEL", DEFAULT_MODEL),
        "language": "es",
        "response_format": "verbose_json",
        "temperature": "0",
        "prompt": build_prompt(vocabulary),
    }
    owns_client = client is None
    client = client or httpx.Client(timeout=30)
    try:
        response = client.post(
            GROQ_TRANSCRIPTIONS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data=data,
            files={"file": (filename, audio, mime_type)},
        )
    except httpx.HTTPError as exc:
        raise TranscriptionError(
            f"Groq request failed: {exc}",
            "No pude transcribir el audio (el servicio no respondió). ¿Podés enviarlo de nuevo en un minuto?",
        ) from exc
    finally:
        if owns_client:
            client.close()

    if response.status_code != 200:
        raise TranscriptionError(
            f"Groq returned {response.status_code}: {response.text[:300]}",
            "No pude transcribir el audio. ¿Podés enviarlo de nuevo en un minuto?",
        )

    body = response.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise TranscriptionError(
            "Groq returned an empty transcript",
            "No logré entender el audio. ¿Podés grabarlo de nuevo, más cerca del teléfono?",
        )
    return Transcript(
        text=text,
        language=body.get("language"),
        duration=body.get("duration"),
        segments=[
            Segment(start=s["start"], end=s["end"], text=s["text"].strip())
            for s in body.get("segments") or []
        ],
    )
