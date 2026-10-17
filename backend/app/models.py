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


# Checked by the API, per patient (a person's role comes from patient_access).
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.caregiver: frozenset({Permission.send_report, Permission.correct_report,
                               Permission.read_reports, Permission.read_care_plan}),
    Role.family: frozenset({Permission.read_reports, Permission.read_care_plan}),
    Role.doctor: frozenset({Permission.read_reports, Permission.read_care_plan,
                            Permission.edit_care_plan}),
    Role.nurse: frozenset({Permission.read_reports, Permission.read_care_plan}),
    Role.institution: frozenset({Permission.read_reports, Permission.read_care_plan}),
    # The patient sees their profile and care plan, never reports about them.
    Role.patient: frozenset({Permission.read_care_plan}),
}


class AlertType(str, enum.Enum):
    omission = "omission"
    change = "change"
    missing_item = "missing_item"


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


class MagicLink(TimestampMixin, Base):
    """Single-use login link. Only the token hash is stored."""

    __tablename__ = "magic_link"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 hex
    person_id: Mapped[str] = mapped_column(ForeignKey("person.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    """One end-of-shift report as received. Written once, never updated."""

    __tablename__ = "report"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rep"))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.id"), nullable=False, index=True)
    caregiver_id: Mapped[str] = mapped_column(ForeignKey("person.id"), nullable=False)
    # Provider message id (WhatsApp/Telegram). UNIQUE makes reprocessing a
    # duplicate delivery fail at the database instead of creating a second report.
    # NULL for reports typed in the web fallback.
    message_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp", nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    # Timestamped transcript segments: [{"start": 0.0, "end": 3.2, "text": "..."}].
    # Used to locate a quote inside the audio for citations.
    segments: Mapped[list] = mapped_column(default=list, nullable=False)
    red_flag: Mapped[bool] = mapped_column(default=False, nullable=False)
    red_flag_terms: Mapped[list] = mapped_column(default=list, nullable=False)

    patient: Mapped[Patient] = relationship(back_populates="reports")
    caregiver: Mapped[Person] = relationship()
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
    report_refs: Mapped[list] = mapped_column(default=list, nullable=False)  # ["rep_121", ...]

    report_version: Mapped[ReportVersion] = relationship(back_populates="alerts")


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


def next_version(session: Session, report_id: str) -> int:
    current = session.scalar(
        select(func.max(ReportVersion.version)).where(ReportVersion.report_id == report_id)
    )
    return (current or 0) + 1
