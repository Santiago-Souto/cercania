"""Routers for the web-facing API; `api_router` is mounted by app.main."""

from fastapi import APIRouter

from app.api import auth, corrections, me, notifications, patients, query, reports

api_router = APIRouter()
for module in (auth, patients, reports, corrections, me, notifications, query):
    api_router.include_router(module.router)
