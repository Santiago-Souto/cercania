"""CercanIA API: HTTP endpoints and the WhatsApp webhook."""

from fastapi import FastAPI

app = FastAPI(title="CercanIA API")


@app.get("/health")
def health() -> dict:
    """Liveness check used by the host and by the team to confirm a deploy."""
    return {"status": "ok", "service": "cercania-api"}
