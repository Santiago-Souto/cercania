"""Web notification inbox routes (no routes yet).

GET /me/notifications?since=<iso>&unread_only=1, POST /me/notifications/{id}/read,
POST /me/notifications/read-all.
"""

from fastapi import APIRouter

router = APIRouter(tags=["notifications"])
