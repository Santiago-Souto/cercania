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
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    """Anyone who logs in: caregivers and family members. Phone = identity."""

    __tablename__ = "person"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("per"))
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # E.164
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)

    access: Mapped[list[PatientAccess]] = relationship(back_populates="person")


class Patient(TimestampMixin, Base):
    """Subject of the record. Not a user; never logs in."""

    __tablename__ = "patient"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pat"))
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    birth_year: Mapped[int | None] = mapped_column(Integer)
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
    """Versioned like reports: a change adds a new plan; old plans stay."""

    __tablename__ = "care_plan"
    __table_args__ = (UniqueConstraint("patient_id", "version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("plan"))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patient.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
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


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "sqlite:///./cercania.db")
    # Supabase hands out postgres:// or postgresql:// URLs; we use the psycopg 3 driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


engine = create_engine(database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Create missing tables. Safe to call repeatedly; never drops anything."""
    Base.metadata.create_all(engine)


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
