"""Shared FastAPI dependencies: database session and the calling person."""

import os
from collections.abc import Iterator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models import SessionLocal


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def current_person_id(request: Request) -> str:
    """Who is calling.

    SIMULATED until the login backend lands (CIA-26): the web app sends the
    person id in the `X-Person-Id` header. Anyone can claim any id, so the
    header is only honored when ALLOW_DEV_IDENTITY_HEADER=1 (local dev, demo
    with fictional data); otherwise every call is 401. Replace the body of this
    function with the session-cookie lookup; endpoints that depend on it do not change.
    """
    if os.environ.get("ALLOW_DEV_IDENTITY_HEADER") != "1":
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthenticated", "message": "El inicio de sesión todavía no está disponible."},
        )
    person_id = request.headers.get("X-Person-Id")
    if not person_id:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthenticated", "message": "Iniciá sesión para continuar."},
        )
    return person_id
