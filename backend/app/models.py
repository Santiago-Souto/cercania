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
    raise_emergency = "raise_emergency"  # WhatsApp message that triage flags as an emergency


# Checked by the API, per patient (a person's role comes from patient_access).
# Every role may raise an emergency; that grants no extra read access.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.caregiver: frozenset({Permission.send_report, Permission.correct_report,
                               Permission.read_reports, Permission.read_care_plan,
                               Permission.raise_emergency}),
    Role.family: frozenset({Permission.read_reports, Permission.read_care_plan,
                            Permission.raise_emergency}),
    Role.doctor: frozenset({Permission.read_reports, Permission.read_care_plan,
                            Permission.edit_care_plan, Permission.raise_emergency}),
    Role.nurse: frozenset({Permission.read_reports, Permission.read_care_plan,
                           Permission.raise_emergency}),
    Role.institution: frozenset({Permission.read_reports, Permission.read_care_plan,
                                 Permission.raise_emergency}),
    # The patient sees their profile and care plan, never reports about them.
    Role.patient: frozenset({Permission.read_care_plan, Permission.raise_emergency}),
}


class AlertType(str, enum.Enum):
    omission = "omission"
    change = "change"
    missing_item = "missing_item"
    emergency = "emergency"  # decided by the model in triage.py (AGENTS.md section 3)


class ReportKind(str, enum.Enum):
    shift = "shift"  # caregiver's report: checklist extraction + comparison
    emergency = "emergency"  # another role raised an emergency: no checklist items


class TriageStatus(str, enum.Enum):
    ok = "ok"
    failed = "failed"  # model error/timeout; the report is stored anyway


class NotificationChannel(str, enum.Enum):
    web = "web"  # in-app inbox (polled by the web)
    whatsapp = "whatsapp"


class NotificationStatus(str, enum.Enum):
    sent = "sent"
    failed = "failed"
    skipped = "skipped"  # channel disabled (e.g. NOTIFY_WHATSAPP=0)


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
    """Anyone who logs in or messages the bot, in any role. Phone = identity; email is unverified contact info."""

    __tablename__ = "person"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("per"))
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # E.164
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254))  # not unique, never grants access

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
    # Registered health provider (not the doctor role). Used only to notify an
    # emergency over WhatsApp; both null = no provider registered.
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


class InviteStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"


class Invite(TimestampMixin, Base):
    """Pending membership for a phone number. Becomes a `patient_access` row when
    that phone verifies a login code (matched on the phone only, never on email)."""

    __tablename__ = "invite"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("inv"))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.id"), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # E.164
    role: Mapped[Role] = mapped_column(enum_column(Role), nullable=False)
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
    # Provider message id (WhatsApp/Telegram). UNIQUE makes reprocessing a
    # duplicate delivery fail at the database instead of creating a second report.
    # NULL for reports typed in the web fallback.
    message_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp", nullable=False)
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
    # `emergency` alerts only: one entry per WhatsApp notification attempted,
    # [{"to": "health_provider"|"caregiver"|"family", "person_id": str|None,
    #   "status": "sent"|"failed", "error": str|None}].
    notifications: Mapped[list] = mapped_column(default=list, nullable=False)

    report_version: Mapped[ReportVersion] = relationship(back_populates="alerts")


class Notification(TimestampMixin, Base):
    """One delivery of an alert to one recipient on one channel (web inbox or WhatsApp).

    `alert.notifications` keeps the summary the contract exposes; this table is the inbox.
    """

    __tablename__ = "notification"
    # Makes dispatch idempotent. person_id is NULL for the health provider; NULLs are
    # distinct in SQL, so dispatch code also checks for existing rows itself.
    __table_args__ = (UniqueConstraint("alert_id", "recipient", "person_id", "channel"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ntf"))
    alert_id: Mapped[int] = mapped_column(ForeignKey("alert.id"), nullable=False, index=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("report.id"), nullable=False)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.id"), nullable=False, index=True)
    person_id: Mapped[str | None] = mapped_column(ForeignKey("person.id"), index=True)  # null = health provider
    recipient: Mapped[str] = mapped_column(String(20), nullable=False)  # health_provider|caregiver|family
    channel: Mapped[NotificationChannel] = mapped_column(enum_column(NotificationChannel), nullable=False)
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
    """Create missing tables and nullable columns. Safe to call repeatedly; never drops anything."""
    Base.metadata.create_all(engine)
    # No migration tool: add nullable columns that were introduced after a table existed.
    existing = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in existing.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have and col.nullable:
                    col_type = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}'))


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
    """Who gets a WhatsApp notification when an emergency is raised (AGENTS.md 4.2).

    The patient's registered health provider (if any), then every caregiver and
    family member with access to the patient. Never the patient themself, the
    doctor role, or the sender (who already got the reply). Decided by code only.
    """
    patient = session.get(Patient, patient_id)
    recipients: list[dict] = []
    if patient is not None and patient.health_provider_phone:
        recipients.append({"to": "health_provider", "person_id": None,
                           "name": patient.health_provider_name,
                           "phone": patient.health_provider_phone})
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


def next_version(session: Session, report_id: str) -> int:
    current = session.scalar(
        select(func.max(ReportVersion.version)).where(ReportVersion.report_id == report_id)
    )
    return (current or 0) + 1
