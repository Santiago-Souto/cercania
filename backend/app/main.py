"""CercanIA API: HTTP endpoints and the WhatsApp webhook."""

import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app import models, storage, web_reports, whatsapp
from app.api import api_router
from app.errors import error_response, install_error_handlers

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


app = FastAPI(title="CercanIA API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=web_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Content-Type", "X-Person-Id"],
)
install_error_handlers(app)
app.include_router(web_reports.router)
app.include_router(api_router)


@app.get("/health")
def health() -> dict:
    """Liveness check used by the host and by the team to confirm a deploy."""
    return {"status": "ok", "service": "cercania-api"}


@app.get("/webhook/whatsapp")
def whatsapp_verify(request: Request):
    """Meta calls this once when the webhook URL is registered."""
    params = request.query_params
    challenge = whatsapp.verify_subscription(
        params.get("hub.mode"), params.get("hub.verify_token"), params.get("hub.challenge")
    )
    if challenge is None:
        return error_response(403, "verification_failed", "Verify token does not match.")
    return PlainTextResponse(challenge)


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, background: BackgroundTasks):
    """Acks immediately; each new message is processed in the background."""
    body = await request.body()
    if not whatsapp.valid_signature(body, request.headers.get("X-Hub-Signature-256")):
        log.warning("Rejected WhatsApp webhook with an invalid signature")
        return error_response(403, "invalid_signature", "Request is not signed by Meta.")
    try:
        payload = json.loads(body)
    except ValueError:
        return error_response(400, "invalid_json", "Body is not JSON.")

    for message in whatsapp.parse_messages(payload):
        if whatsapp.seen_messages.first_time(message.id):
            background.add_task(whatsapp.handle_message, message)
        else:
            log.info("Duplicate delivery of %s ignored", message.id)
    return {"status": "received"}
