import httpx

from app import whatsapp
from app.transcribe import Transcript, TranscriptionError
from app.whatsapp import IncomingMessage


def audio_msg():
    return IncomingMessage(id="wamid.1", sender="5491122334455", type="audio", audio_id="media-1", audio_mime="audio/ogg")


def capture(monkeypatch):
    sent, transcripts = [], []
    monkeypatch.setattr(whatsapp, "send_text", lambda to, text: sent.append((to, text)))
    monkeypatch.setattr(whatsapp, "handle_transcript", lambda m, t: transcripts.append(t.text))
    return sent, transcripts


def test_voice_note_is_downloaded_and_transcribed(monkeypatch):
    sent, transcripts = capture(monkeypatch)
    monkeypatch.setattr(whatsapp, "download_media", lambda media_id: (b"OggS", "audio/ogg; codecs=opus"))
    calls = []

    def fake_transcribe(audio, mime_type, **kw):
        calls.append((audio, mime_type))
        return Transcript(text="comió poco en la cena")

    monkeypatch.setattr(whatsapp, "transcribe", fake_transcribe)
    whatsapp.handle_message(audio_msg())
    assert calls == [(b"OggS", "audio/ogg")]
    assert transcripts == ["comió poco en la cena"]
    assert sent == []


def test_download_failure_tells_the_caregiver(monkeypatch):
    sent, transcripts = capture(monkeypatch)

    def fail(media_id):
        raise whatsapp.DownloadError("404")

    monkeypatch.setattr(whatsapp, "download_media", fail)
    whatsapp.handle_message(audio_msg())
    assert sent == [("5491122334455", whatsapp.MSG_DOWNLOAD_FAILED)]
    assert transcripts == []


def test_transcription_failure_tells_the_caregiver(monkeypatch):
    sent, transcripts = capture(monkeypatch)
    monkeypatch.setattr(whatsapp, "download_media", lambda media_id: (b"OggS", "audio/ogg"))

    def fail(*a, **kw):
        raise TranscriptionError("500", "No pude transcribir el audio.")

    monkeypatch.setattr(whatsapp, "transcribe", fail)
    whatsapp.handle_message(audio_msg())
    assert sent == [("5491122334455", "No pude transcribir el audio.")]
    assert transcripts == []


def test_unexpected_error_still_tells_the_caregiver(monkeypatch):
    sent, _ = capture(monkeypatch)

    def boom(media_id):
        raise RuntimeError("bug")

    monkeypatch.setattr(whatsapp, "download_media", boom)
    whatsapp.handle_message(audio_msg())
    assert len(sent) == 1 and "error inesperado" in sent[0][1]


def test_text_report_is_used_as_transcript(monkeypatch):
    sent, transcripts = capture(monkeypatch)
    whatsapp.handle_message(IncomingMessage(id="w2", sender="54911", type="text", text="  durmió bien  "))
    assert transcripts == ["durmió bien"]
    assert sent == []


def test_unsupported_message_asks_for_a_voice_note(monkeypatch):
    sent, transcripts = capture(monkeypatch)
    whatsapp.handle_message(IncomingMessage(id="w3", sender="54911", type="image"))
    assert sent == [("54911", whatsapp.MSG_UNSUPPORTED)]
    assert transcripts == []


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
