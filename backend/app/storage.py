"""Supabase Storage for report audio (CIA-44): private bucket, short-lived signed URLs.

Plain REST over httpx (no SDK). The bucket is private: objects are only reachable
through a signed URL the API creates after checking the caller's access. The
service key is backend-only and never logged.

Config: SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_BUCKET (default "media").
Without URL and key, nothing is stored (configured() is False) and audio_url stays null.
"""

from __future__ import annotations

import os
from urllib.parse import quote

import httpx

DEFAULT_BUCKET = "media"
SIGNED_URL_TTL_SEC = 300
TIMEOUT_SEC = 15.0

# File extension per stored MIME type; anything else is kept as .bin.
EXTENSIONS = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/aac": "aac",
    "audio/amr": "amr",
}


class StorageError(Exception):
    """Storage call failed or is not configured. The message never contains the key."""


def _config() -> tuple[str, str, str] | None:
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    bucket = os.environ.get("SUPABASE_BUCKET", "").strip() or DEFAULT_BUCKET
    return (url, key, bucket) if url and key else None


def configured() -> bool:
    return _config() is not None


def _headers(key: str) -> dict[str, str]:
    headers = {"apikey": key}
    # Legacy service_role keys are JWTs and also go as a bearer token. New secret
    # keys (sb_secret_...) are not JWTs: the gateway accepts them only as `apikey`.
    if not key.startswith("sb_"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def audio_path(patient_id: str, report_id: str, mime_type: str) -> str:
    """One object per report: re-uploading the same report overwrites, never duplicates."""
    return f"reports/{patient_id}/{report_id}.{EXTENSIONS.get(mime_type, 'bin')}"


def _request(method: str, endpoint: str, *, client: httpx.Client | None, **kwargs) -> httpx.Response:
    config = _config()
    if config is None:
        raise StorageError("storage is not configured (SUPABASE_URL / SUPABASE_SERVICE_KEY)")
    url, key, _ = config
    headers = {**_headers(key), **kwargs.pop("headers", {})}
    owns_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SEC)
    try:
        response = client.request(method, f"{url}/storage/v1/{endpoint}", headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        raise StorageError(f"{method} storage failed: {type(exc).__name__}") from exc
    finally:
        if owns_client:
            client.close()
    if response.status_code >= 300:
        raise StorageError(f"{method} storage returned {response.status_code}: {response.text[:200]}")
    return response


def _object(path: str) -> str:
    _, _, bucket = _config() or ("", "", DEFAULT_BUCKET)
    return f"{quote(bucket)}/{quote(path)}"


def upload(path: str, data: bytes, mime_type: str, *, client: httpx.Client | None = None) -> None:
    _request("POST", f"object/{_object(path)}", client=client, content=data,
             headers={"Content-Type": mime_type, "x-upsert": "true"})


def signed_url(path: str, expires_in: int = SIGNED_URL_TTL_SEC, *, client: httpx.Client | None = None) -> str:
    """Full URL that plays the object for `expires_in` seconds, with no other credential."""
    response = _request("POST", f"object/sign/{_object(path)}", client=client, json={"expiresIn": expires_in})
    try:
        signed = response.json()["signedURL"]
    except (ValueError, KeyError, TypeError) as exc:
        raise StorageError("sign response had no signedURL") from exc
    url, _, _ = _config()
    return f"{url}/storage/v1{signed}" if signed.startswith("/") else signed
