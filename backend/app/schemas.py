"""Pydantic models for every endpoint: response models (so /docs documents the contract)
and request bodies. They mirror docs/contract.md; change them only together with it.
"""

from __future__ import annotations

from datetime import datetime as _datetime, timezone
from typing import Literal

from pydantic import AfterValidator, BaseModel, Field, StringConstraints
from typing_extensions import Annotated


def _as_utc(value: _datetime) -> _datetime:
    # SQLite hands back naive datetimes (stored as UTC). Without an offset the
    # browser would read them as local time, so every timestamp leaves with one.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


datetime = Annotated[_datetime, AfterValidator(_as_utc)]

ChecklistItemName = Literal[
    "appetite", "sleep", "urination", "medication", "mood", "mobility", "pain", "incidents"
]
RoleName = Literal["caregiver", "family", "doctor", "nurse", "institution", "patient"]


class Medication(BaseModel):
    id: str
    name: str
    dose: str
    times: list[str]


class CarePlan(BaseModel):
    medications: list[Medication]
    indications: list[str]
    allergies: list[str]


class Patient(BaseModel):
    id: str
    display_name: str
    location: str | None = None
    care_plan: CarePlan | None = None


class Triage(BaseModel):
    status: str
    emergency: bool
    reason: str | None = None
    quote: str | None = None
    quote_verified: bool | None = None


class ReportItem(BaseModel):
    item: str
    value: str | None = None
    level: str | None = None
    details: dict | None = None
    quote: str | None = None
    quote_verified: bool | None = None
    audio_start_sec: float | None = None
    audio_end_sec: float | None = None
    source: str | None = None


class NotificationSummary(BaseModel):
    to: str
    person_id: str | None = None
    channel: str | None = None
    status: str
    error: str | None = None


class Alert(BaseModel):
    id: int
    type: str
    item: str | None = None
    detail: str
    plan_ref: str | None = None
    evidence_quote: str | None = None
    evidence_verified: bool | None = None
    report_refs: list[str] = []
    notifications: list[NotificationSummary] = []
    report_id: str | None = None
    report_version: int | None = None
    created_at: datetime | None = None


class Person(BaseModel):
    id: str
    display_name: str
    role: str | None = None


class Report(BaseModel):
    id: str
    version: int
    created_at: datetime
    kind: str
    channel: str
    sender: Person
    caregiver: Person  # compat alias of `sender` (web/lib/types.ts)
    transcript: str
    audio_url: str | None = None
    audio_duration_sec: float | None = None
    items: list[ReportItem]
    missing_items: list[str]
    alerts: list[Alert]
    red_flag: bool
    red_flag_quote: str | None = None
    triage: Triage | None = None
    confirmation_text: str | None = None


class ReportsPage(BaseModel):
    reports: list[Report]
    next_before: datetime | None = None


class ReportVersion(BaseModel):
    version: int
    source: str
    created_at: datetime
    created_by: Person
    items: list[ReportItem]
    missing_items: list[str]
    alerts: list[Alert]
    confirmation_text: str | None = None


class ReportVersions(BaseModel):
    report_id: str
    versions: list[ReportVersion]


class CorrectionIn(BaseModel):
    item: ChecklistItemName
    value: str | None = None


class CorrectionsRequest(BaseModel):
    corrections: list[CorrectionIn] = Field(min_length=1)


class QueryRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class Citation(BaseModel):
    report_id: str
    quote: str
    audio_start_sec: float | None = None
    audio_end_sec: float | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    confidence: Literal["answered", "unclear"]
    note: str | None = None


class Membership(BaseModel):
    patient_id: str
    display_name: str
    role: RoleName


class Me(BaseModel):
    id: str
    display_name: str
    phone_last4: str
    memberships: list[Membership]


class MyPatient(BaseModel):
    id: str
    display_name: str
    location: str | None = None
    role: RoleName
    # null for role "patient": the patient never sees reports or alerts.
    last_report_at: datetime | None = None
    open_alerts: int | None = None
    red_flag: bool | None = None
    missing_report: bool | None = None


class MyPatients(BaseModel):
    patients: list[MyPatient]


class Notification(BaseModel):
    id: str
    patient_id: str
    patient_display_name: str
    alert_id: int
    report_id: str
    recipient: str
    channel: str
    status: str
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None = None


class NotificationsPage(BaseModel):
    notifications: list[Notification]
    unread_count: int
