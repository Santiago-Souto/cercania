import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import ingest, whatsapp
from app.models import Base, CarePlan, Medication, Patient, PatientAccess, Person, Role
from app.transcribe import Transcript, TranscriptionError
from app.whatsapp import IncomingMessage

ANA = "15550100001"     # caregiver of one patient
BRUNO = "15550100002"   # caregiver of two patients
CARMEN = "15550100011"  # family only
STRANGER = "15550109999"


@pytest.fixture(autouse=True)
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        s.add_all([
            Patient(id="pat_rosa", display_name="Rosa (ficticia)", vocabulary=["andador"]),
            Patient(id="pat_jorge", display_name="Jorge (ficticio)"),
            Patient(id="pat_elena", display_name="Elena (ficticia)"),
            CarePlan(id="plan_rosa", patient_id="pat_rosa", version=1),
            Medication(id="med_1", care_plan_id="plan_rosa", name="Enalapril", dose_text="1 comprimido", times=["08:00"]),
            Person(id="ana", phone="+" + ANA, display_name="Ana"),
            Person(id="bruno", phone="+" + BRUNO, display_name="Bruno"),
            Person(id="carmen", phone="+" + CARMEN, display_name="Carmen"),
            PatientAccess(person_id="ana", patient_id="pat_rosa", role=Role.caregiver),
            PatientAccess(person_id="bruno", patient_id="pat_jorge", role=Role.caregiver),
            PatientAccess(person_id="bruno", patient_id="pat_elena", role=Role.caregiver),
            PatientAccess(person_id="carmen", patient_id="pat_rosa", role=Role.family),
        ])
        s.commit()
    monkeypatch.setattr(whatsapp, "session_factory", factory)
    monkeypatch.setattr(whatsapp, "pending_choices", whatsapp.PendingChoices())


@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(whatsapp, "send_text", lambda to, text: messages.append((to, text)))
    return messages


class Calls(list):
    """Calls to the fake process_report; `.result` is what it returns."""


@pytest.fixture
def brain(monkeypatch):
    calls = Calls()
    calls.result = {"status": "ok", "confirmation_text": "Registré: comió poco. ¿Cómo durmió?", "red_flag": False}

    def fake(**kwargs):
        calls.append(kwargs)
        return dict(calls.result)

    monkeypatch.setattr(ingest, "process_report", fake)
    return calls


@pytest.fixture
def media(monkeypatch):
    transcribed = []
    monkeypatch.setattr(whatsapp, "download_media", lambda media_id: (b"OggS", "audio/ogg; codecs=opus"))

    def fake_transcribe(audio, mime_type, vocabulary):
        transcribed.append({"mime_type": mime_type, "vocabulary": vocabulary})
        return Transcript(text="comió poco en la cena")

    monkeypatch.setattr(whatsapp, "transcribe", fake_transcribe)
    return transcribed


def voice(sender, message_id="wamid.v1"):
    return IncomingMessage(id=message_id, sender=sender, type="audio", audio_id="media-1", audio_mime="audio/ogg")


def text(sender, body, message_id="wamid.t1"):
    return IncomingMessage(id=message_id, sender=sender, type="text", text=body)


def test_voice_note_from_caregiver_with_one_patient_is_processed_and_confirmed(sent, brain, media):
    whatsapp.handle_message(voice(ANA))
    assert media == [{"mime_type": "audio/ogg", "vocabulary": ["andador", "Enalapril"]}]
    assert brain == [{
        "patient_id": "pat_rosa", "sender_id": "ana", "transcript": "comió poco en la cena",
        "audio_ref": None, "message_id": "wamid.v1",
    }]
    assert sent == [(ANA, "Registré: comió poco. ¿Cómo durmió?")]


def test_unknown_number_gets_a_clear_message(sent, brain, media):
    whatsapp.handle_message(voice(STRANGER))
    assert sent == [(STRANGER, whatsapp.MSG_UNKNOWN_NUMBER)]
    assert brain == [] and media == []


def test_person_without_reporting_role_is_told(sent, brain, media):
    whatsapp.handle_message(voice(CARMEN))
    assert sent == [(CARMEN, whatsapp.MSG_NO_PATIENTS)]
    assert brain == []


def test_argentine_number_matches_without_mobile_digit(sent, brain, media, db):
    with whatsapp.session_factory() as s:
        s.add(Person(id="ar", phone="+541122334455", display_name="AR"))
        s.add(PatientAccess(person_id="ar", patient_id="pat_elena", role=Role.caregiver))
        s.commit()
    whatsapp.handle_message(voice("5491122334455"))
    assert brain[0]["sender_id"] == "ar"


def test_several_patients_asks_which_then_processes_the_kept_note(sent, brain, media):
    whatsapp.handle_message(voice(BRUNO, "wamid.report"))
    assert brain == [] and media == []
    question = sent[-1][1]
    assert "¿De qué paciente" in question
    assert "1. Elena (ficticia)" in question and "2. Jorge (ficticio)" in question

    whatsapp.handle_message(text(BRUNO, "2", "wamid.answer"))
    assert brain[0]["patient_id"] == "pat_jorge"
    assert brain[0]["message_id"] == "wamid.report"  # the report's id, not the answer's
    assert sent[-1] == (BRUNO, "Registré: comió poco. ¿Cómo durmió?")


def test_patient_can_be_chosen_by_name_without_accents(sent, brain, media):
    whatsapp.handle_message(text(BRUNO, "durmió mal", "wamid.r"))
    whatsapp.handle_message(text(BRUNO, "elena", "wamid.a"))
    assert brain[0]["patient_id"] == "pat_elena"
    assert brain[0]["transcript"] == "durmió mal"


def test_invalid_choice_asks_again(sent, brain, media):
    whatsapp.handle_message(voice(BRUNO))
    whatsapp.handle_message(text(BRUNO, "7", "wamid.a"))
    assert brain == []
    assert "¿De qué paciente" in sent[-1][1]


def test_red_flag_adds_fixed_emergency_line(sent, brain, media):
    brain.result["red_flag"] = True
    whatsapp.handle_message(voice(ANA))
    assert sent[-1][1].startswith(whatsapp.MSG_RED_FLAG)
    assert "Registré: comió poco" in sent[-1][1]


def test_needs_retry_sends_the_message_from_the_result(sent, brain, media):
    brain.result.clear()
    brain.result.update({"status": "needs_retry", "message": "No pude procesarlo, ¿lo mandás de nuevo?"})
    whatsapp.handle_message(voice(ANA))
    assert sent[-1] == (ANA, "No pude procesarlo, ¿lo mandás de nuevo?")


def test_without_process_report_the_caregiver_is_told_nothing_was_stored(sent, media):
    whatsapp.handle_message(voice(ANA))  # real ingest: app.process does not exist yet
    assert sent == [(ANA, whatsapp.MSG_PROCESSING_UNAVAILABLE)]


def test_download_failure_tells_the_caregiver(sent, brain, monkeypatch):
    def fail(media_id):
        raise whatsapp.DownloadError("404")

    monkeypatch.setattr(whatsapp, "download_media", fail)
    whatsapp.handle_message(voice(ANA))
    assert sent == [(ANA, whatsapp.MSG_DOWNLOAD_FAILED)]
    assert brain == []


def test_transcription_failure_tells_the_caregiver(sent, brain, monkeypatch):
    monkeypatch.setattr(whatsapp, "download_media", lambda media_id: (b"OggS", "audio/ogg"))

    def fail(*a, **kw):
        raise TranscriptionError("500", "No pude transcribir el audio.")

    monkeypatch.setattr(whatsapp, "transcribe", fail)
    whatsapp.handle_message(voice(ANA))
    assert sent == [(ANA, "No pude transcribir el audio.")]
    assert brain == []


def test_unexpected_error_still_tells_the_caregiver(sent, brain, monkeypatch):
    def boom(media_id):
        raise RuntimeError("bug")

    monkeypatch.setattr(whatsapp, "download_media", boom)
    whatsapp.handle_message(voice(ANA))
    assert sent == [(ANA, whatsapp.MSG_UNEXPECTED)]


def test_unsupported_message_asks_for_a_voice_note(sent, brain):
    whatsapp.handle_message(IncomingMessage(id="w3", sender=ANA, type="image"))
    assert sent == [(ANA, whatsapp.MSG_UNSUPPORTED)]
    assert brain == []


def test_transcript_and_full_phone_never_reach_the_logs(sent, brain, caplog):
    caplog.set_level("DEBUG")
    whatsapp.handle_message(text(ANA, "tiene dolor en el pecho"))
    assert brain  # processed
    assert "dolor" not in caplog.text
    assert ANA not in caplog.text
    assert "***0001" in caplog.text


def test_download_media_follows_graph_url_with_bearer_token():
    seen = []

    def handler(request: httpx.Request):
        seen.append((str(request.url), request.headers["Authorization"]))
        if request.url.host == "graph.facebook.com":
            return httpx.Response(200, json={"url": "https://lookaside.example/audio", "mime_type": "audio/ogg"})
        return httpx.Response(200, content=b"OggS")

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        audio, mime = whatsapp.download_media("media-1", client=c)
    assert (audio, mime) == (b"OggS", "audio/ogg")
    assert seen[0][0].endswith("/media-1")
    assert all(auth == "Bearer test-token" for _, auth in seen)


def test_send_text_retries_argentine_number_without_mobile_digit():
    recipients = []

    def handler(request: httpx.Request):
        import json

        to = json.loads(request.content)["to"]
        recipients.append(to)
        if to == "5491122334455":
            return httpx.Response(400, json={"error": {"code": whatsapp.RECIPIENT_NOT_ALLOWED}})
        return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert whatsapp.send_text("5491122334455", "hola", client=c) is True
    assert recipients == ["5491122334455", "541122334455"]


def test_send_text_returns_false_on_other_errors():
    def handler(request):
        return httpx.Response(401, json={"error": {"code": 190, "message": "expired token"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert whatsapp.send_text("5491122334455", "hola", client=c) is False


def test_send_text_without_credentials_logs_instead_of_crashing(monkeypatch):
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID")
    assert whatsapp.send_text("5491122334455", "hola") is False


def test_send_text_returns_false_on_non_json_error_body():
    def handler(request):
        return httpx.Response(502, content=b"<html>Bad gateway</html>")

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert whatsapp.send_text("5491122334455", "hola", client=c) is False


def test_malformed_message_logs_keys_not_content(caplog):
    caplog.set_level("DEBUG")
    payload = {"entry": [{"changes": [{"value": {"messages": [{"type": "text", "text": {"body": "dato privado"}}]}}]}]}
    assert whatsapp.parse_messages(payload) == []
    assert "dato privado" not in caplog.text


def test_second_report_while_choosing_is_queued_not_lost(sent, brain, media):
    whatsapp.handle_message(voice(BRUNO, "wamid.first"))
    whatsapp.handle_message(voice(BRUNO, "wamid.second"))
    assert brain == []
    assert sent[-1][1].startswith(whatsapp.MSG_QUEUED)

    whatsapp.handle_message(text(BRUNO, "1", "wamid.a1"))  # Elena for the first
    assert [c["message_id"] for c in brain] == ["wamid.first"]
    assert brain[0]["patient_id"] == "pat_elena"
    assert sent[-1][1].startswith(whatsapp.MSG_NEXT_PENDING)

    whatsapp.handle_message(text(BRUNO, "jorge", "wamid.a2"))
    assert [c["message_id"] for c in brain] == ["wamid.first", "wamid.second"]
    assert brain[1]["patient_id"] == "pat_jorge"
    assert whatsapp.pending_choices.first(BRUNO) is None


def test_typed_report_while_choosing_is_queued_not_taken_as_a_bad_answer(sent, brain, media):
    whatsapp.handle_message(voice(BRUNO, "wamid.first"))
    whatsapp.handle_message(text(BRUNO, "Jorge durmió mal toda la noche y no quiso cenar", "wamid.typed"))
    assert sent[-1][1].startswith(whatsapp.MSG_QUEUED)
    whatsapp.handle_message(text(BRUNO, "2", "wamid.a1"))
    whatsapp.handle_message(text(BRUNO, "2", "wamid.a2"))
    assert [c["message_id"] for c in brain] == ["wamid.first", "wamid.typed"]
    assert brain[1]["transcript"] == "Jorge durmió mal toda la noche y no quiso cenar"


def test_expired_reports_are_reported_to_the_caregiver(sent, brain, media, monkeypatch):
    monkeypatch.setattr(whatsapp, "pending_choices", whatsapp.PendingChoices(ttl_seconds=-1))
    whatsapp.handle_message(voice(BRUNO, "wamid.old"))
    whatsapp.handle_message(text(BRUNO, "1", "wamid.late"))
    assert brain == []
    assert any(whatsapp.MSG_EXPIRED.format(count=1) == t for _, t in sent)


def test_question_says_number_or_name(sent, brain, media):
    whatsapp.handle_message(voice(BRUNO))
    assert "Respondé con el número o el nombre" in sent[-1][1]
