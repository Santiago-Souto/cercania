"""Current-person routes (no routes yet).

GET /me (person + memberships) and GET /me/patients (MyPatient list).
"""

from fastapi import APIRouter

router = APIRouter(tags=["me"])
