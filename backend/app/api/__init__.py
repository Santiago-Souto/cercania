"""Routers for the web-facing API; `api_router` is mounted by app.main."""

from fastapi import APIRouter

from app.api import corrections, me, notifications, patients, query, reports

api_router = APIRouter()
for module in (patients, reports, corrections, me, notifications, query):
    api_router.include_router(module.router)
