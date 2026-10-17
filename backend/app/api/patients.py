"""Patient read routes (no routes yet; filled by the read-routes step).

GET /patients/{id} (read_care_plan), GET /patients/{id}/reports?limit=20&before=<iso> (read_reports),
GET /patients/{id}/alerts?since=<iso>&limit=50 (read_reports). See docs/backend-routes-plan.md.
"""

from fastapi import APIRouter

router = APIRouter(tags=["patients"])
