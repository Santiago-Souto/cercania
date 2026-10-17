"""Corrections route (no routes yet).

POST /reports/{id}/corrections (correct_report): adds a new report_version authored by the caller.
"""

from fastapi import APIRouter

router = APIRouter(tags=["corrections"])
