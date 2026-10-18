"""CercanIA API: HTTP endpoints."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models, patient_messages, storage, web_reports
from app.api import api_router
from app.errors import install_error_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    models.init_db()  # create_all: creates missing tables, never drops
    if not storage.configured():
        log.warning("SUPABASE_URL / SUPABASE_SERVICE_KEY not set: report audio is not stored")
    yield


def web_origins(raw: str | None = None) -> list[str]:
    """Browser origins allowed to call the API (WEB_ORIGINS, comma-separated).

    Fails closed: unset or empty allows no origin, so a deploy that forgets the
    variable blocks browsers instead of trusting a default. Credentials are on,
    so "*" is never valid here.
    """
    raw = os.environ.get("WEB_ORIGINS", "") if raw is None else raw
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    if not origins:
        log.warning("WEB_ORIGINS is not set: browsers cannot call the API")
    return [o for o in origins if o != "*"]


def cors_headers() -> list[str]:
    """Request headers browsers may send. `X-Person-Id` is the simulated dev identity
    (deps.current_person_id), so it is allowed only when that fallback is on."""
    if os.environ.get("ALLOW_DEV_IDENTITY_HEADER") == "1":
        return ["Content-Type", "X-Person-Id"]
    return ["Content-Type"]


app = FastAPI(title="CercanIA API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=web_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=cors_headers(),
)
install_error_handlers(app)
app.include_router(web_reports.router)
app.include_router(patient_messages.router)
app.include_router(api_router)


@app.get("/health")
def health() -> dict:
    """Liveness check used by the host and by the team to confirm a deploy."""
    return {"status": "ok", "service": "cercania-api"}
