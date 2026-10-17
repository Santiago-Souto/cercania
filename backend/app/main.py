"""CercanIA API: HTTP endpoints and the WhatsApp webhook."""

import json
import logging

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app import whatsapp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="CercanIA API")


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


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
        return error(403, "verification_failed", "Verify token does not match.")
    return PlainTextResponse(challenge)


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, background: BackgroundTasks):
    """Acks immediately; each new message is processed in the background."""
    body = await request.body()
    if not whatsapp.valid_signature(body, request.headers.get("X-Hub-Signature-256")):
        log.warning("Rejected WhatsApp webhook with an invalid signature")
        return error(403, "invalid_signature", "Request is not signed by Meta.")
    try:
        payload = json.loads(body)
    except ValueError:
        return error(400, "invalid_json", "Body is not JSON.")

    for message in whatsapp.parse_messages(payload):
        if whatsapp.seen_messages.first_time(message.id):
            background.add_task(whatsapp.handle_message, message)
        else:
            log.info("Duplicate delivery of %s ignored", message.id)
    return {"status": "received"}
