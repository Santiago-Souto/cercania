"""Report audio in object storage (CIA-44): storage REST calls, store_audio, GET /reports/{id}/audio."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import ingest, storage
from app.deps import get_db
from app.main import app
from app.models import Base, File, FileKind, Patient, PatientAccess, Person, Report, Role

JWT_KEY = "eyJhbGciOiJIUzI1NiJ9.fake.sig"
SB_KEY = "sb_secret_fake"


@pytest.fixture
def supabase(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co/")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", JWT_KEY)
    monkeypatch.delenv("SUPABASE_BUCKET", raising=False)


def recording_client(status=200, body=None):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body if body is not None else {"Key": "media/x"})

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


# --- storage.py ---------------------------------------------------------------------------


def test_not_configured_without_url_and_key():
    assert storage.configured() is False
    with pytest.raises(storage.StorageError, match="not configured"):
        storage.upload("reports/p/r.ogg", b"OggS", "audio/ogg")


def test_upload_posts_bytes_to_the_private_bucket(supabase):
    client, seen = recording_client()
    storage.upload("reports/pat_1/rep_1.webm", b"\x1aE", "audio/webm", client=client)
    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == "https://proj.supabase.co/storage/v1/object/media/reports/pat_1/rep_1.webm"
    assert req.headers["content-type"] == "audio/webm"
    assert req.headers["x-upsert"] == "true"
    assert req.headers["apikey"] == JWT_KEY and req.headers["authorization"] == f"Bearer {JWT_KEY}"
    assert req.content == b"\x1aE"


def test_new_secret_keys_go_only_as_apikey(supabase, monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", SB_KEY)
    monkeypatch.setenv("SUPABASE_BUCKET", "audio-test")
    client, seen = recording_client()
    storage.upload("reports/p/r.ogg", b"OggS", "audio/ogg", client=client)
    assert seen[0].headers["apikey"] == SB_KEY
    assert "authorization" not in seen[0].headers
    assert "/object/audio-test/" in str(seen[0].url)


def test_signed_url_is_absolute_and_short_lived(supabase):
    client, seen = recording_client(body={"signedURL": "/object/sign/media/reports/p/r.ogg?token=abc"})
    url = storage.signed_url("reports/p/r.ogg", client=client)
    assert url == "https://proj.supabase.co/storage/v1/object/sign/media/reports/p/r.ogg?token=abc"
    assert str(seen[0].url).endswith("/storage/v1/object/sign/media/reports/p/r.ogg")
    assert json.loads(seen[0].content) == {"expiresIn": storage.SIGNED_URL_TTL_SEC}


def test_errors_never_include_the_key(supabase):
    client, _ = recording_client(status=403, body={"message": "new row violates row-level security policy"})
    with pytest.raises(storage.StorageError) as exc:
        storage.upload("reports/p/r.ogg", b"OggS", "audio/ogg", client=client)
    assert "403" in str(exc.value) and JWT_KEY not in str(exc.value)
    client, _ = recording_client(body={"unexpected": True})
    with pytest.raises(storage.StorageError, match="signedURL"):
        storage.signed_url("reports/p/r.ogg", client=client)


def test_audio_path_one_object_per_report():
    assert storage.audio_path("pat_1", "rep_1", "audio/ogg") == "reports/pat_1/rep_1.ogg"
    assert storage.audio_path("pat_1", "rep_1", "audio/mp4") == "reports/pat_1/rep_1.m4a"
    assert storage.audio_path("pat_1", "rep_1", "audio/unknown") == "reports/pat_1/rep_1.bin"


# --- database fixtures ----------------------------------------------------------------------


@pytest.fixture
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    make = sessionmaker(bind=engine, expire_on_commit=False)
    with make() as s:
        s.add(Patient(id="pat_x", display_name="Rosa (ficticia)"))
        for pid, role in [("cg", Role.caregiver), ("fam", Role.family), ("pat", Role.patient)]:
            s.add(Person(id=pid, phone=f"+1555020000{len(pid)}{pid}", display_name=pid))
            s.add(PatientAccess(person_id=pid, patient_id="pat_x", role=role))
        s.add(Person(id="other", phone="+15550299999", display_name="other"))
        s.add(Report(id="rep_1", patient_id="pat_x", sender_id="cg", message_id="wa-1", transcript="t"))
        s.add(Report(id="rep_2", patient_id="pat_x", sender_id="cg", message_id="wa-2", transcript="t"))
        s.commit()
    return make


@pytest.fixture
def uploads(monkeypatch):
    calls = []
    monkeypatch.setattr(storage, "upload", lambda path, data, mime: calls.append((path, data, mime)))
    return calls


OK = {"status": "ok", "report": {"id": "rep_1", "version": 1}}
VOICE = ingest.Audio(b"OggS-voice", "audio/ogg", 12.8)


def files(factory):
    with factory() as s:
        return s.scalars(select(File)).all()


# --- ingest.store_audio ---------------------------------------------------------------------


def test_store_audio_uploads_once_and_records_the_file(supabase, factory, uploads):
    assert ingest.store_audio(OK, VOICE, session_factory=factory) is True
    assert uploads == [("reports/pat_x/rep_1.ogg", b"OggS-voice", "audio/ogg")]
    [f] = files(factory)
    assert (f.kind, f.report_id, f.patient_id, f.uploaded_by) == (FileKind.audio, "rep_1", "pat_x", "cg")
    assert (f.storage_path, f.mime_type, f.size_bytes, f.duration_sec) == ("reports/pat_x/rep_1.ogg", "audio/ogg", 10, 12.8)
    # A repeated delivery of the same message: no second upload, no second row.
    assert ingest.store_audio(OK, VOICE, session_factory=factory) is False
    assert len(uploads) == 1 and len(files(factory)) == 1


@pytest.mark.parametrize("result", [
    {"status": "needs_retry", "message": "x"},
    {"status": "not_a_report", "message": "x"},
    {"status": "forbidden", "message": "x"},
    {"status": "ok"},
    None,
])
def test_store_audio_skips_results_without_a_stored_report(supabase, factory, uploads, result):
    assert ingest.store_audio(result, VOICE, session_factory=factory) is False
    assert uploads == [] and files(factory) == []


def test_store_audio_skips_typed_reports_and_missing_config(factory, uploads, monkeypatch):
    assert ingest.store_audio(OK, VOICE, session_factory=factory) is False  # not configured
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", JWT_KEY)
    assert ingest.store_audio(OK, None, session_factory=factory) is False  # typed report
    assert uploads == [] and files(factory) == []


def test_failed_upload_keeps_the_report_and_logs_ids_only(supabase, factory, monkeypatch, caplog):
    def boom(path, data, mime):
        raise storage.StorageError("POST storage returned 500: oops")

    monkeypatch.setattr(storage, "upload", boom)
    assert ingest.store_audio(OK, VOICE, session_factory=factory) is False
    assert files(factory) == []
    with factory() as s:
        assert s.get(Report, "rep_1") is not None
    assert "rep_1" in caplog.text and "OggS" not in caplog.text and JWT_KEY not in caplog.text


# --- GET /reports/{id}/audio and the Report shape --------------------------------------------


client = TestClient(app)


@pytest.fixture
def api(factory, monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADER", "1")
    session = factory()
    with session:
        session.add(File(patient_id="pat_x", uploaded_by="cg", report_id="rep_1", kind=FileKind.audio,
                         storage_path="reports/pat_x/rep_1.ogg", mime_type="audio/ogg", duration_sec=12.8))
        session.commit()
    session = factory()
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.clear()
    session.close()


@pytest.fixture
def signer(monkeypatch):
    calls = []

    def fake(path):
        calls.append(path)
        return f"https://proj.supabase.co/storage/v1/object/sign/media/{path}?token=t"

    monkeypatch.setattr(storage, "signed_url", fake)
    return calls


@pytest.mark.parametrize("person", ["cg", "fam"])
def test_audio_endpoint_returns_a_signed_url(api, signer, person):
    r = client.get("/reports/rep_1/audio", headers={"X-Person-Id": person})
    assert r.status_code == 200
    assert r.json() == {"url": "https://proj.supabase.co/storage/v1/object/sign/media/reports/pat_x/rep_1.ogg?token=t",
                        "expires_in_sec": storage.SIGNED_URL_TTL_SEC}
    assert signer == ["reports/pat_x/rep_1.ogg"]


def test_audio_endpoint_access_rules(api, signer):
    assert client.get("/reports/rep_1/audio", headers={"X-Person-Id": "pat"}).status_code == 403
    no_access = client.get("/reports/rep_1/audio", headers={"X-Person-Id": "other"})
    assert no_access.status_code == 404 and no_access.json()["error"]["code"] == "not_found"
    no_audio = client.get("/reports/rep_2/audio", headers={"X-Person-Id": "cg"})
    assert no_audio.status_code == 404 and no_audio.json()["error"]["code"] == "not_found"
    assert client.get("/reports/nope/audio", headers={"X-Person-Id": "cg"}).status_code == 404
    assert signer == []


def test_audio_endpoint_storage_failure_is_a_clear_502(api, monkeypatch):
    def boom(path):
        raise storage.StorageError("storage is not configured")

    monkeypatch.setattr(storage, "signed_url", boom)
    r = client.get("/reports/rep_1/audio", headers={"X-Person-Id": "cg"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "audio_unavailable"


def test_report_shape_points_audio_url_at_the_endpoint(api):
    with_audio = client.get("/reports/rep_1", headers={"X-Person-Id": "cg"}).json()
    assert with_audio["audio_url"] == "/reports/rep_1/audio" and with_audio["audio_duration_sec"] == 12.8
    without = client.get("/reports/rep_2", headers={"X-Person-Id": "cg"}).json()
    assert without["audio_url"] is None and without["audio_duration_sec"] is None


def test_file_rows_count_is_unchanged_by_reads(api, signer):
    client.get("/reports/rep_1/audio", headers={"X-Person-Id": "cg"})
    assert api.scalar(select(func.count()).select_from(File)) == 1


def test_store_audio_never_raises_on_database_errors(supabase, uploads):
    def broken_factory():
        raise RuntimeError("database is down")

    assert ingest.store_audio(OK, VOICE, session_factory=broken_factory) is False
    assert uploads == []
