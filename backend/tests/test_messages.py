"""Family <-> health team messages (CIA-36): human to human, family and health team only."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import llm
from app.api import messages as messages_api
from app.deps import get_db
from app.main import app
from app.models import Base, Message, MessageRead, Patient, PatientAccess, Person, Role

URL = "/patients/pat_x/messages"
client = TestClient(app)


def as_(person):
    return {"X-Person-Id": person}


@pytest.fixture(autouse=True)
def dev_identity(monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_IDENTITY_HEADER", "1")


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("messages must never call the model")

    monkeypatch.setattr(llm, "complete_json", boom)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add(Patient(id="pat_x", display_name="Rosa (ficticia)"))
    session.add(Patient(id="pat_y", display_name="Otro (ficticio)"))
    for i, (pid, role) in enumerate([("fam", Role.family), ("doc", Role.doctor), ("nur", Role.nurse),
                                     ("cg", Role.caregiver), ("ptl", Role.patient)]):
        session.add(Person(id=pid, phone=f"+1555040000{i}", display_name=pid.upper()))
        session.add(PatientAccess(person_id=pid, patient_id="pat_x", role=role))
    session.add(Person(id="other", phone="+15550409999", display_name="other"))
    session.add(PatientAccess(person_id="other", patient_id="pat_y", role=Role.family))
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.clear()
    session.close()


def test_family_sends_doctor_replies_both_see_thread(db):
    r = client.post(URL, json={"text": "  Hola doctora, ¿cómo durmió?  "}, headers=as_("fam"))
    assert r.status_code == 201
    sent = r.json()
    assert sent["text"] == "Hola doctora, ¿cómo durmió?"
    assert sent["from"] == {"user_id": "fam", "name": "FAM", "role": "family"}
    assert sent["read"] is False

    thread = client.get(URL, headers=as_("doc")).json()["messages"]
    assert [m["text"] for m in thread] == ["Hola doctora, ¿cómo durmió?"]
    assert thread[0]["read"] is False  # new for the doctor on this first listing

    client.post(URL, json={"text": "Durmió bien."}, headers=as_("doc"))
    thread = client.get(URL, headers=as_("fam")).json()["messages"]
    assert [(m["from"]["role"], m["text"]) for m in thread] == [("family", "Hola doctora, ¿cómo durmió?"),
                                                                ("doctor", "Durmió bien.")]
    assert thread[0]["read"] is True  # the doctor opened the thread after it arrived
    assert thread[1]["read"] is False  # new for the family member
    assert len(db.scalars(select(Message)).all()) == 2


def test_listing_twice_does_not_duplicate_reads(db):
    client.post(URL, json={"text": "Hola"}, headers=as_("fam"))
    client.get(URL, headers=as_("doc"))
    second = client.get(URL, headers=as_("doc")).json()["messages"]
    assert second[0]["read"] is True
    assert len(db.scalars(select(MessageRead)).all()) == 1


def test_mark_read_skips_duplicates(db):
    client.post(URL, json={"text": "Hola"}, headers=as_("fam"))
    msg_id = db.scalars(select(Message)).one().id
    messages_api._mark_read(db, [msg_id], "doc")
    messages_api._mark_read(db, [msg_id], "doc")
    assert len(db.scalars(select(MessageRead)).all()) == 1


@pytest.mark.parametrize("person", ["cg", "ptl"])
def test_caregiver_and_patient_are_forbidden(db, person):
    assert client.get(URL, headers=as_(person)).status_code == 403
    r = client.post(URL, json={"text": "hola"}, headers=as_(person))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"
    assert db.scalars(select(Message)).all() == []


def test_no_access_is_not_found(db):
    assert client.get(URL, headers=as_("other")).status_code == 404
    assert client.post(URL, json={"text": "hola"}, headers=as_("other")).status_code == 404


def test_unauthenticated(db):
    assert client.get(URL).status_code == 401


@pytest.mark.parametrize("body", [{"text": "   "}, {"text": "x" * 2001}, {}])
def test_rejects_empty_or_too_long(db, body):
    r = client.post(URL, json=body, headers=as_("nur"))
    assert r.status_code in (400, 422)
    assert "error" in r.json()
    assert db.scalars(select(Message)).all() == []


def test_threads_are_per_patient(db):
    client.post(URL, json={"text": "solo pat_x"}, headers=as_("fam"))
    assert client.get("/patients/pat_y/messages", headers=as_("other")).json() == {"messages": []}
