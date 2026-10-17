"""Shared FastAPI dependencies: database session and the calling person."""

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
    person id in the `X-Person-Id` header. Replace the body of this function
    with the session-cookie lookup; endpoints that depend on it do not change.
    """
    person_id = request.headers.get("X-Person-Id")
    if not person_id:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthenticated", "message": "Iniciá sesión para continuar."},
        )
    return person_id
