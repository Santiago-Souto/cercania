import httpx
import pytest

from app import transcribe as t


def mock_client(status=200, body=None, record=None):
    def handler(request: httpx.Request):
        if record is not None:
            record.append(request)
        return httpx.Response(status, json=body if body is not None else {})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_sends_model_language_and_vocabulary_hint():
    requests = []
    body = {
        "text": " Comió poco. ",
        "language": "spanish",
        "duration": 3.2,
        "segments": [{"start": 0.0, "end": 1.5, "text": " Comió poco."}],
        "words": [{"word": "Comió", "start": 0.0, "end": 0.6}, {"word": " poco.", "start": 0.6, "end": 1.5}],
    }
    with mock_client(body=body, record=requests) as c:
        result = t.transcribe(b"OggS", vocabulary=["Enalapril"], client=c)

    assert result.text == "Comió poco."
    assert result.segments == [t.Segment(start=0.0, end=1.5, text="Comió poco.")]
    assert result.words == [t.Segment(0.0, 0.6, "Comió"), t.Segment(0.6, 1.5, "poco.")]
    # Words are what gets stored: a quote maps to exactly its words.
    assert result.segment_dicts() == [{"start": 0.0, "end": 0.6, "text": "Comió"},
                                      {"start": 0.6, "end": 1.5, "text": "poco."}]
    sent = requests[0].content.decode(errors="ignore")
    assert requests[0].headers["Authorization"] == "Bearer groq-test"
    assert "whisper-large-v3-turbo" in sent
    assert "verbose_json" in sent
    assert sent.count('name="timestamp_granularities[]"') == 2 and "word" in sent
    assert "Enalapril" in sent and "diuresis" in sent


def test_prompt_is_bounded_and_keeps_the_end():
    words = [f"palabra{i:03d}" for i in range(200)]  # distinct, so dedupe keeps them all
    prompt = t.build_prompt(words)
    assert len(prompt) == t.MAX_PROMPT_CHARS
    assert prompt.endswith("palabra199.")  # Whisper reads the end of the prompt


def test_missing_key_gives_user_message(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    with pytest.raises(t.TranscriptionError) as exc:
        t.transcribe(b"OggS")
    assert exc.value.user_message


def test_api_error_gives_user_message():
    with mock_client(status=500, body={"error": "boom"}) as c, pytest.raises(t.TranscriptionError) as exc:
        t.transcribe(b"OggS", client=c)
    assert "transcribir" in exc.value.user_message


def test_empty_transcript_is_an_error_not_a_guess():
    with mock_client(body={"text": "  "}) as c, pytest.raises(t.TranscriptionError):
        t.transcribe(b"OggS", client=c)


def test_without_word_timestamps_segments_are_stored():
    body = {"text": "Comió poco.", "segments": [{"start": 0.0, "end": 1.5, "text": " Comió poco."}]}
    with mock_client(body=body) as c:
        result = t.transcribe(b"OggS", client=c)
    assert result.words == []
    assert result.segment_dicts() == [{"start": 0.0, "end": 1.5, "text": "Comió poco."}]
