"""Database schema (SQLAlchemy 2.0).

One relational database (Postgres on Supabase; SQLite for local dev) holds every
structured fact. Binary files (audio, images, documents) live in object storage
(Supabase Storage); the `file` table only stores where to find them.

Evidence-trail rules (AGENTS.md section 5):
- `report` is the logical report: original audio, transcript, sender, message id.
  It is written once and never updated.
- `report_version` holds what was recorded for that report. A correction adds a
  new version; earlier versions are never modified.
- Every `report_item` keeps the verbatim quote it came from and whether code
  verified that quote against the transcript.
"""

from __future__ import annotations

import enum
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    inspect,
    select,
    text,
)
from dotenv import find_dotenv, load_dotenv
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

# JSONB on Postgres, plain JSON on SQLite.
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Opaque string ids with a readable prefix, e.g. 'rep_3f9a1c2b7d4e'."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def enum_column(enum_cls: type[enum.Enum]) -> Enum:
    # Stored as VARCHAR + CHECK so it behaves the same on Postgres and SQLite.
    return Enum(
        enum_cls,
        native_enum=False,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
        length=32,
    )


# --- Enums -------------------------------------------------------------------


class ChecklistItem(str, enum.Enum):
    """Fixed checklist (docs/contract.md). Edit together with the contract."""

    appetite = "appetite"
    sleep = "sleep"
    urination = "urination"
    medication = "medication"
    mood = "mood"
    mobility = "mobility"
    pain = "pain"
    incidents = "incidents"


class Role(str, enum.Enum):
    caregiver = "caregiver"
    family = "family"
    doctor = "doctor"
    nurse = "nurse"  # health team, like doctor but cannot edit the care plan
    institution = "institution"  # health team, like nurse
    patient = "patient"  # the patient's own login, linked to their profile


class Permission(str, enum.Enum):
    send_report = "send_report"
    correct_report = "correct_report"
    read_reports = "read_reports"  # reports, items, alerts, cited query
    read_care_plan = "read_care_plan"
    edit_care_plan = "edit_care_plan"  # creates a new care_plan version
    raise_emergency = "raise_emergency"  # message that triage flags as an emergency
    send_patient_message = "send_patient_message"  # "how I feel" / "I need help" (AGENTS.md 6)
    read_patient_messages = "read_patient_messages"
    invite = "invite"  # POST /patients/{id}/invites, by phone number only
    edit_emergency_contact = "edit_emergency_contact"  # PATCH /patients/{id}/emergency-contact (CIA-51)
    team_messages = "team_messages"  # family <-> health team thread, human to human (CIA-36)


# Checked by the API, per patient (a person's role comes from patient_access).
# Every role may raise an emergency; that grants no extra read access.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    # Caregivers may also send patient messages, to test the patient view (docs/contract.md).
    Role.caregiver: frozenset({Permission.send_report, Permission.correct_report,
                               Permission.read_reports, Permission.read_care_plan,
                               Permission.raise_emergency, Permission.send_patient_message,
                               Permission.read_patient_messages, Permission.invite,
                               Permission.edit_emergency_contact}),
    # Family <-> health team messages: only those roles, never caregiver or patient (AGENTS.md 6).
    Role.family: frozenset({Permission.read_reports, Permission.read_care_plan,
                            Permission.raise_emergency, Permission.team_messages}),
    Role.doctor: frozenset({Permission.read_reports, Permission.read_care_plan,
                            Permission.edit_care_plan, Permission.edit_emergency_contact,
                            Permission.raise_emergency, Permission.read_patient_messages,
                            Permission.team_messages}),
    Role.nurse: frozenset({Permission.read_reports, Permission.read_care_plan,
                           Permission.raise_emergency, Permission.read_patient_messages,
                           Permission.team_messages}),
    Role.institution: frozenset({Permission.read_reports, Permission.read_care_plan,
                                 Permission.raise_emergency, Permission.read_patient_messages,
                                 Permission.team_messages}),
    # The patient sees their profile, care plan and own messages, never reports about them.
    Role.patient: frozenset({Permission.read_care_plan, Permission.raise_emergency,
                             Permission.send_patient_message, Permission.read_patient_messages}),
}


class AlertType(str, enum.Enum):
    omission = "omission"
    change = "change"
    missing_item = "missing_item"
    emergency = "emergency"  # decided by the model in triage.py (AGENTS.md section 3)


class ReportKind(str, enum.Enum):
    shift = "shift"  # caregiver's report: checklist extraction + comparison
    emergency = "emergency"  # another role raised an emergency: no checklist items


class PatientMessageKind(str, enum.Enum):
    feeling = "feeling"  # how the patient feels: triaged by the model
    help = "help"  # "I need help": fixed rule, never the model (AGENTS.md 7)


class TriageStatus(str, enum.Enum):
    ok = "ok"
    failed = "failed"  # model error/timeout; the report is stored anyway


class NotificationChannel(str, enum.Enum):
    web = "web"  # in-app inbox (polled by the web); the only channel


class NotificationStatus(str, enum.Enum):
    sent = "sent"
    failed = "failed"
    skipped = "skipped"  # legacy rows only; nothing writes it now


class FileKind(str, enum.Enum):
    audio = "audio"
    image = "image"
    document = "document"


class VersionSource(str, enum.Enum):
    original = "original"  # first processing of the voice note / text
    correction = "correction"  # caregiver corrected one or more items


class ItemSource(str, enum.Enum):
    transcript = "transcript"  # extracted by the model, quote checked by code
    correction = "correction"  # typed by the caregiver; no quote


# --- Base --------------------------------------------------------------------


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONType, list: JSONType}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


# --- People and access -------------------------------------------------------


class Person(TimestampMixin, Base):
    """Anyone who logs in, in any role. Phone = identity; email is unverified contact info."""

    __tablename__ = "person"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("per"))
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # E.164
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254))  # not unique, never grants access
    # Global admin (CIA-48): lists people and assigns roles, nothing else. Set by hand in the
    # database, from an admin pre-registration at sign-up, or by another admin (confirmed).
    # Nullable so init_db can add it to an existing table; NULL = false.
    is_admin: Mapped[bool | None] = mapped_column(default=False)
    # Caregiver granted by an admin before any patient is assigned (pre-registered without a
    # patient). Lets them create patients and keeps sign-up from making them a patient.
    is_caregiver: Mapped[bool | None] = mapped_column(default=False)

    access: Mapped[list[PatientAccess]] = relationship(back_populates="person")


class Patient(TimestampMixin, Base):
    """Subject of the record. Not a user; never logs in."""

    __tablename__ = "patient"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pat"))
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    birth_year: Mapped[int | None] = mapped_column(Integer)
    location: Mapped[str | None] = mapped_column(String(120))  # e.g. "Habitación 12"
    notes: Mapped[str | None] = mapped_column(Text)
    # Extra words for the transcription hint (names, local terms). Medication
    # names are added automatically from the active care plan.
    vocabulary: Mapped[list] = mapped_column(default=list, nullable=False)
    # Emergency contact (name + phone; API: `emergency_contact`). Shown as contact
    # information only: it has no inbox, so it is not notified; both null = none registered.
    health_provider_name: Mapped[str | None] = mapped_column(String(120))
    health_provider_phone: Mapped[str | None] = mapped_column(String(20))  # E.164

    access: Mapped[list[PatientAccess]] = relationship(back_populates="patient")
    care_plans: Mapped[list[CarePlan]] = relationship(
        back_populates="patient", order_by="CarePlan.version"
    )
    reports: Mapped[list[Report]] = relationship(back_populates="patient")


class PatientAccess(TimestampMixin, Base):
    """Who can see which patient, and in which role.

    One person can be caregiver for one patient and family for another.
    A patient who logs in has a `person` row with role `patient` on their own profile.
    """

    __tablename__ = "patient_access"
    __table_args__ = (UniqueConstraint("person_id", "patient_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("person.id"), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.id"), nullable=False)
    role: Mapped[Role] = mapped_column(enum_column(Role), nullable=False)

    person: Mapped[Person] = relationship(back_populates="access")
    patient: Mapped[Patient] = relationship(back_populates="access")


class LoginCode(TimestampMixin, Base):
    """6-digit code sent by SMS (api/auth.py). Only a salted hash of the code is stored.

    A sign-up code carries the name and email typed at sign-up: the person row is
    created only when the code is verified, so nobody can claim a phone without it.
    """

    __tablename__ = "login_code"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # E.164
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # hmac-sha256 hex
    salt: Mapped[str] = mapped_column(String(32), nullable=False)
    signup_name: Mapped[str | None] = mapped_column(String(120))
    signup_email: Mapped[str | None] = mapped_column(String(254))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(TimestampMixin, Base):
    """Web session behind the cookie. Only the token hash is stored."""

    __tablename__ = "auth_session"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 hex
    person_id: Mapped[str] = mapped_column(ForeignKey("person.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PreRegistration(TimestampMixin, Base):
    """A role an admin assigned to a phone that has not signed up yet (CIA-48).

    Nothing is sent. When that phone verifies its sign-up code, the role is applied and the
    row is deleted (the role_change log keeps the history). `role` is a Role value or "admin";
    `patient_id` is required for family/doctor/nurse/institution, optional for caregiver,
    unused for admin and patient.
    """

    __tablename__ = "pre_registration"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pre"))
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # E.164
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patient.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("person.id"), nullable=False)


class RoleChange(Base):
    """Audit log of every role change made by an admin or applied at sign-up (CIA-48)."""

    __tablename__ = "role_change"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("person.id"))  # the admin
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    person_id: Mapped[str | None] = mapped_column(ForeignKey("person.id"))
    phone: Mapped[str | None] = mapped_column(String(20))
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patient.id"))
    before: Mapped[dict | None] = mapped_column(JSONType)
    after: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class InviteStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"


class Invite(TimestampMixin, Base):
    """Pending membership for a phone number. Becomes a `patient_access` row only when the
    person with that phone accepts it in the app (POST /me/invites/{id}/accept; matched on
    the phone their session proved, never on email). Declining deletes the row."""

    __tablename__ = "invite"
    # At most one pending invite per patient and phone, even under concurrent requests.
    __table_args__ = (
        Index("uq_invite_pending", "patient_id", "phone", unique=True,
              sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("inv"))
    # NULL only for a `patient` invite to someone without a profile yet (CIA-48): accepting it
    # creates their patient profile and makes `invited_by` its caregiver.
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patient.id"))
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # E.164
    role: Mapped[Role] = mapped_column(enum_column(Role), nullable=False)  # family or patient (CIA-48)
    invited_by: Mapped[str | None] = mapped_column(ForeignKey("person.id"))
    status: Mapped[InviteStatus] = mapped_column(
        enum_column(InviteStatus), default=InviteStatus.pending, nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Care plan -----------------------------------------------------------------


class CarePlan(TimestampMixin, Base):
    """Versioned like reports: a change adds a new plan; old plans stay.

    Only a person with `edit_care_plan` (doctor) may create a version.
    """

    __tablename__ = "care_plan"
    __table_args__ = (UniqueConstraint("patient_id", "version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("plan"))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("person.id"))
    indications: Mapped[list] = mapped_column(default=list, nullable=False)  # list[str]
    allergies: Mapped[list] = mapped_column(default=list, nullable=False)  # list[str]

    patient: Mapped[Patient] = relationship(back_populates="care_plans")
    medications: Mapped[list[Medication]] = relationship(
        back_populates="care_plan", order_by="Medication.id"
    )


class Medication(Base):
    """Separate table because alerts reference it by id (`plan_ref`).

    `dose_text` is copied from the plan as text. Code never computes or changes it.
    """

    __tablename__ = "medication"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("med"))
    care_plan_id: Mapped[str] = mapped_column(ForeignKey("care_plan.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    dose_text: Mapped[str] = mapped_column(String(120), nullable=False)
    times: Mapped[list] = mapped_column(default=list, nullable=False)  # ["08:00", "20:00"]

    care_plan: Mapped[CarePlan] = relationship(back_populates="medications")


# --- Files (pointers into object storage) -----------------------------------------


class File(TimestampMixin, Base):
    """Metadata for a binary stored in Supabase Storage (or local disk in dev).

    The bytes are never stored in the database. To serve a file, the backend
    creates a short-lived signed URL from `storage_path`.
    """

    __tablename__ = "file"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("file"))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.id"), nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("person.id"))
    report_id: Mapped[str | None] = mapped_column(ForeignKey("report.id"))
    kind: Mapped[FileKind] = mapped_column(enum_column(FileKind), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    duration_sec: Mapped[float | None] = mapped_column(Float)  # audio only


# --- Reports -----------------------------------------------------------------------


class Report(TimestampMixin, Base):
    """One message as received: a caregiver's shift report, or an emergency raised
    by another role. Written once, never updated.

    An `emergency` report still gets a version 1 (with no items) so its alert has
    a version to hang from, like every other alert.
    """

    __tablename__ = "report"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rep"))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.id"), nullable=False, index=True)
    # Whoever sent the message (any role; a caregiver for `shift` reports).
    sender_id: Mapped[str] = mapped_column(ForeignKey("person.id"), nullable=False)
    kind: Mapped[ReportKind] = mapped_column(
        enum_column(ReportKind), default=ReportKind.shift, nullable=False
    )
    # Client message id (`web:<person>:<client_id>`). UNIQUE makes reprocessing a
    # duplicate delivery fail at the database instead of creating a second report.
    message_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    channel: Mapped[str] = mapped_column(String(20), default="web", nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    # Timestamped transcript segments: [{"start": 0.0, "end": 3.2, "text": "..."}].
    # Used to locate a quote inside the audio for citations.
    segments: Mapped[list] = mapped_column(default=list, nullable=False)
    # Triage result (triage.py). red_flag == the model said "emergency".
    # triage_status is NULL only for seed fixtures, which never went through triage.
    red_flag: Mapped[bool] = mapped_column(default=False, nullable=False)
    triage_status: Mapped[TriageStatus | None] = mapped_column(enum_column(TriageStatus))
    triage_reason: Mapped[str | None] = mapped_column(Text)
    triage_quote: Mapped[str | None] = mapped_column(Text)
    triage_quote_verified: Mapped[bool | None] = mapped_column()
    triage_model: Mapped[str | None] = mapped_column(String(64))

    patient: Mapped[Patient] = relationship(back_populates="reports")
    sender: Mapped[Person] = relationship()
    files: Mapped[list[File]] = relationship()
    versions: Mapped[list[ReportVersion]] = relationship(
        back_populates="report", order_by="ReportVersion.version"
    )

    @property
    def audio(self) -> File | None:
        return next((f for f in self.files if f.kind == FileKind.audio), None)

    @property
    def latest(self) -> ReportVersion | None:
        return self.versions[-1] if self.versions else None


class ReportVersion(TimestampMixin, Base):
    """What was recorded for a report at one point in time. Immutable."""

    __tablename__ = "report_version"
    __table_args__ = (UniqueConstraint("report_id", "version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rv"))
    report_id: Mapped[str] = mapped_column(ForeignKey("report.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[VersionSource] = mapped_column(enum_column(VersionSource), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("person.id"), nullable=False)
    # Raw model output kept as evidence of what the model actually returned.
    extraction_raw: Mapped[dict | None] = mapped_column(JSONType)
    model: Mapped[str | None] = mapped_column(String(64))
    confirmation_text: Mapped[str | None] = mapped_column(Text)

    report: Mapped[Report] = relationship(back_populates="versions")
    items: Mapped[list[ReportItem]] = relationship(
        back_populates="report_version", order_by="ReportItem.id"
    )
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="report_version", order_by="Alert.id"
    )

    @property
    def missing_items(self) -> list[str]:
        return [i.item.value for i in self.items if i.value is None]


class ReportItem(Base):
    """One checklist item inside a report version.

    Every checklist item gets a row; `value is None` means it was not mentioned.
    """

    __tablename__ = "report_item"
    __table_args__ = (
        UniqueConstraint("report_version_id", "item"),
        CheckConstraint(
            "(quote IS NULL AND quote_verified IS NULL) OR quote IS NOT NULL",
            name="quote_verified_needs_quote",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_version_id: Mapped[str] = mapped_column(
        ForeignKey("report_version.id"), nullable=False, index=True
    )
    item: Mapped[ChecklistItem] = mapped_column(enum_column(ChecklistItem), nullable=False)
    value: Mapped[str | None] = mapped_column(Text)  # short human-readable summary
    # Coarse category that compare.py uses to detect changes over time, e.g.
    # appetite: "normal" | "low" | "none". Allowed values live in extract.py.
    level: Mapped[str | None] = mapped_column(String(32))
    # Item-specific structure, e.g. medication:
    # {"doses": [{"plan_ref": "med_002", "time": "08:00", "given": true}]}
    details: Mapped[dict | None] = mapped_column(JSONType)
    quote: Mapped[str | None] = mapped_column(Text)  # verbatim from transcript
    quote_verified: Mapped[bool | None] = mapped_column()
    audio_start_sec: Mapped[float | None] = mapped_column(Float)
    audio_end_sec: Mapped[float | None] = mapped_column(Float)
    source: Mapped[ItemSource] = mapped_column(
        enum_column(ItemSource), default=ItemSource.transcript, nullable=False
    )

    report_version: Mapped[ReportVersion] = relationship(back_populates="items")


class Alert(TimestampMixin, Base):
    """Produced by compare.py (code, no model)."""

    __tablename__ = "alert"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_version_id: Mapped[str] = mapped_column(
        ForeignKey("report_version.id"), nullable=False, index=True
    )
    type: Mapped[AlertType] = mapped_column(enum_column(AlertType), nullable=False)
    item: Mapped[ChecklistItem | None] = mapped_column(enum_column(ChecklistItem))
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    plan_ref: Mapped[str | None] = mapped_column(ForeignKey("medication.id"))
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    evidence_verified: Mapped[bool | None] = mapped_column()
    report_refs: Mapped[list] = mapped_column(default=list, nullable=False)  # ["rep_121", ...]
    # `emergency` alerts only: one entry per web inbox notification,
    # [{"to": "caregiver"|"family", "person_id": str|None,
    #   "status": "sent"|"failed", "error": str|None}].
    notifications: Mapped[list] = mapped_column(default=list, nullable=False)

    report_version: Mapped[ReportVersion] = relationship(back_populates="alerts")


class PatientMessage(TimestampMixin, Base):
    """What the patient sent from their view: how they feel, or "I need help" (AGENTS.md 6-7).

    `help` never goes through the model. `feeling` (text, or the transcript of audio) goes
    through triage; red_flag == the model said emergency. Written once.
    """

    __tablename__ = "patient_message"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pm"))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.id"), nullable=False, index=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("person.id"), nullable=False)
    kind: Mapped[PatientMessageKind] = mapped_column(enum_column(PatientMessageKind), nullable=False)
    text: Mapped[str | None] = mapped_column(Text)  # null for help
    from_audio: Mapped[bool] = mapped_column(default=False, nullable=False)
    red_flag: Mapped[bool] = mapped_column(default=False, nullable=False)
    triage_status: Mapped[TriageStatus | None] = mapped_column(enum_column(TriageStatus))  # null for help
    triage_reason: Mapped[str | None] = mapped_column(Text)
    triage_quote: Mapped[str | None] = mapped_column(Text)
    triage_quote_verified: Mapped[bool | None] = mapped_column()
    triage_model: Mapped[str | None] = mapped_column(String(64))

    seen: Mapped[list[PatientMessageSeen]] = relationship(order_by="PatientMessageSeen.seen_at")


class PatientMessageSeen(Base):
    """A team member saw a patient message (listing the messages marks them seen)."""

    __tablename__ = "patient_message_seen"
    __table_args__ = (UniqueConstraint("patient_message_id", "person_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_message_id: Mapped[str] = mapped_column(ForeignKey("patient_message.id"), nullable=False, index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("person.id"), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    person: Mapped[Person] = relationship()


class Message(TimestampMixin, Base):
    """Family <-> health team thread, one per patient (AGENTS.md 7). Human to human: the
    model never reads or answers these. Written once."""

    __tablename__ = "message"
    # A retry after an ambiguous failure (timeout) sends the same client_id: stored once.
    __table_args__ = (UniqueConstraint("sender_id", "client_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("msg"))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.id"), nullable=False, index=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("person.id"), nullable=False)
    sender_role: Mapped[Role] = mapped_column(enum_column(Role), nullable=False)  # role when sent
    text: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str | None] = mapped_column(String(64))

    sender: Mapped[Person] = relationship()
    reads: Mapped[list[MessageRead]] = relationship(order_by="MessageRead.read_at")


class MessageRead(Base):
    """Someone other than the sender listed the thread after this message arrived."""

    __tablename__ = "message_read"
    __table_args__ = (UniqueConstraint("message_id", "person_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("message.id"), nullable=False, index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("person.id"), nullable=False)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Notification(TimestampMixin, Base):
    """One delivery of an alert to one recipient on one channel (the web inbox).

    `alert.notifications` keeps the summary the contract exposes; this table is the inbox.
    """

    __tablename__ = "notification"
    # Makes dispatch idempotent; dispatch code also checks for existing rows itself.
    __table_args__ = (UniqueConstraint("alert_id", "recipient", "person_id", "channel"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ntf"))
    # Set for emergency alerts on a report; NULL for patient messages (then patient_message_id is set).
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alert.id"), index=True)
    report_id: Mapped[str | None] = mapped_column(ForeignKey("report.id"))
    patient_message_id: Mapped[str | None] = mapped_column(ForeignKey("patient_message.id"), index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.id"), nullable=False, index=True)
    person_id: Mapped[str | None] = mapped_column(ForeignKey("person.id"), index=True)  # null on legacy rows only
    # caregiver | family (emergencies); caregiver | doctor | nurse | institution (patient messages)
    recipient: Mapped[str] = mapped_column(String(20), nullable=False)
    # Plain string, not an enum: databases created while other channels existed still hold rows
    # (and a CHECK) with retired values, and those rows must keep loading. New rows are "web".
    channel: Mapped[str] = mapped_column(String(32), default=NotificationChannel.web.value, nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(enum_column(NotificationStatus), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Engine and helpers ----------------------------------------------------------


# Local dev reads the repo-root .env; in deploy the host sets real env vars,
# which take precedence (override=False).
load_dotenv(find_dotenv(usecwd=True), override=False)

DEFAULT_DATABASE_URL = "sqlite:///./cercania.db"


def database_url(raw: str | None = None) -> str:
    url = raw if raw is not None else os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    # Supabase hands out postgres:// or postgresql:// URLs; we use the psycopg 3 driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def engine_options(url: str) -> dict:
    """Connection settings per backend.

    Supabase (see docs "Connecting to Postgres"):
    - Use the session pooler (port 5432, user postgres.<ref>) from IPv4-only hosts
      such as Render; the direct connection is IPv6 unless the IPv4 add-on is on.
    - SSL must be `require`; drivers default to `prefer`, which can fall back to plaintext.
    - The transaction pooler (port 6543) does not support prepared statements, so
      psycopg's automatic preparation is turned off there.
    """
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        return {"connect_args": {"check_same_thread": False}}

    connect_args: dict = {}
    if parsed.host not in (None, "localhost", "127.0.0.1") and "sslmode" not in parsed.query:
        connect_args["sslmode"] = "require"
    if parsed.port == 6543:
        connect_args["prepare_threshold"] = None
    # Small pool: the free-tier pooler caps client connections.
    return {"connect_args": connect_args, "pool_pre_ping": True,
            "pool_size": 5, "max_overflow": 5, "pool_recycle": 300}


def describe_database(url: str) -> str:
    """Human-readable target without the password, for logs and errors."""
    return make_url(url).render_as_string(hide_password=True)


engine = create_engine(database_url(), **engine_options(database_url()))
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Create missing tables and nullable columns, and relax NOT NULL where the model became
    nullable (Postgres). Safe to call repeatedly; never drops anything."""
    Base.metadata.create_all(engine)
    # create_all adds indexes only with new tables; add ones introduced later (e.g. uq_invite_pending).
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            for index in table.indexes:
                index.create(conn, checkfirst=True)
    # No migration tool: add nullable columns that were introduced after a table existed.
    existing = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in existing.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have and col.nullable:
                    col_type = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}'))
            # e.g. notification.alert_id / report_id became nullable for patient messages (CIA-29).
            # SQLite cannot alter a column: delete an old local database file instead.
            if engine.dialect.name == "postgresql":
                db_nullable = {c["name"]: c["nullable"] for c in existing.get_columns(table.name)}
                for col in table.columns:
                    if col.nullable and db_nullable.get(col.name) is False:
                        conn.execute(text(f'ALTER TABLE "{table.name}" ALTER COLUMN "{col.name}" DROP NOT NULL'))


def role_for(session: Session, person_id: str, patient_id: str) -> Role | None:
    return session.scalar(
        select(PatientAccess.role).where(
            PatientAccess.person_id == person_id, PatientAccess.patient_id == patient_id
        )
    )


def can(session: Session, person_id: str, patient_id: str, permission: Permission) -> bool:
    role = role_for(session, person_id, patient_id)
    return role is not None and permission in ROLE_PERMISSIONS[role]


def active_care_plan(session: Session, patient_id: str) -> CarePlan | None:
    return session.scalars(
        select(CarePlan)
        .where(CarePlan.patient_id == patient_id)
        .order_by(CarePlan.version.desc())
        .limit(1)
    ).first()


def emergency_recipients(session: Session, patient_id: str, sender_id: str) -> list[dict]:
    """Who gets a web inbox notification when an emergency is raised (AGENTS.md 4.2).

    Every caregiver and family member with access to the patient. Never the patient
    themself, the doctor role, or the sender (who already got the reply). Decided by
    code only. The patient's emergency contact has no inbox, so it is not here.
    """
    recipients: list[dict] = []
    rows = session.execute(
        select(PatientAccess.role, Person)
        .join(Person, Person.id == PatientAccess.person_id)
        .where(PatientAccess.patient_id == patient_id,
               PatientAccess.role.in_([Role.caregiver, Role.family]),
               Person.id != sender_id)
        .order_by(PatientAccess.role, Person.id)
    ).all()
    for role, person in rows:
        recipients.append({"to": role.value, "person_id": person.id,
                           "name": person.display_name, "phone": person.phone})
    return recipients


# Health team roles (AGENTS.md 6).
HEALTH_TEAM = (Role.doctor, Role.nurse, Role.institution)


def patient_team(session: Session, patient_id: str, sender_id: str) -> list[dict]:
    """Who is notified of a patient's help request or red-flag message (AGENTS.md 7).

    Every caregiver and health-team member with access to the patient. Never family,
    never the patient, never the sender (a caregiver testing the patient view). Code only.
    """
    rows = session.execute(
        select(PatientAccess.role, Person)
        .join(Person, Person.id == PatientAccess.person_id)
        .where(PatientAccess.patient_id == patient_id,
               PatientAccess.role.in_([Role.caregiver, *HEALTH_TEAM]),
               Person.id != sender_id)
        .order_by(PatientAccess.role, Person.id)
    ).all()
    return [{"to": role.value, "person_id": person.id, "name": person.display_name, "phone": person.phone}
            for role, person in rows]


def next_version(session: Session, report_id: str) -> int:
    current = session.scalar(
        select(func.max(ReportVersion.version)).where(ReportVersion.report_id == report_id)
    )
    return (current or 0) + 1
