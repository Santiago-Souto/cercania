"""Cited natural-language query route (no routes yet).

POST /patients/{id}/query (read_reports): question -> answer + verified citations.
"""

from fastapi import APIRouter

router = APIRouter(tags=["query"])
