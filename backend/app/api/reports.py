"""Report read routes (no routes yet).

GET /reports/{id} (latest version) and GET /reports/{id}/versions (oldest first); both need
read_reports on the report's patient.
"""

from fastapi import APIRouter

router = APIRouter(tags=["reports"])
