import json
import os
from types import SimpleNamespace

import httpx
import pytest

from app.llm import LLMError, complete_json, parse_model

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
          "additionalProperties": False}


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr("app.llm.RETRY_DELAY_SEC", 0)


def call(model: str, client):
    return complete_json(system="sys", user="usr", schema=SCHEMA, model=model,
                         max_tokens=100, timeout=5, effort="low", client=client)


# --- model spec ----------------------------------------------------------------


@pytest.mark.parametrize("spec, expected", [
    ("claude-haiku-5-5", ("anthropic", "claude-haiku-5-5")),
    ("anthropic:claude-haiku-5-5", ("anthropic", "claude-haiku-5-5")),
    ("openai:gpt-x", ("openai", "gpt-x")),
    ("openai:llama3.1:8b", ("openai", "llama3.1:8b")),  # Ollama tags keep their colon
    ("groq:openai/gpt-oss-120b", ("groq", "openai/gpt-oss-120b")),
])
def test_parse_model(spec, expected):
    assert parse_model(spec) == expected


@pytest.mark.parametrize("spec", ["grok:grok-4", "groq:", "deepseek:deepseek-chat"])
def test_parse_model_rejects_unknown_provider_instead_of_sending_to_anthropic(spec):
    with pytest.raises(LLMError) as e:
        parse_model(spec)
    assert e.value.kind == "config"


def test_anthropic_missing_key_is_a_config_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(LLMError) as e:
        call("anthropic:claude-haiku-5-5", None)  # real SDK path, fails before any request
    assert e.value.kind == "config"


# --- Anthropic adapter (fake client: tests only) --------------------------------


class FakeAnthropic:
    def __init__(self, text=None, stop_reason="end_turn", exc=None):
        self.calls = []
        self._exc = exc
        content = [SimpleNamespace(type="text", text=text)] if text is not None else []
        self._response = SimpleNamespace(stop_reason=stop_reason, content=content)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc:
            raise self._exc
        return self._response


def test_anthropic_sends_schema_and_effort():
    client = FakeAnthropic('{"ok": true}')
    assert call("anthropic:m", client) == {"ok": True}
    sent = client.calls[0]
    assert sent["model"] == "m"
    assert sent["output_config"] == {"effort": "low",
                                     "format": {"type": "json_schema", "schema": SCHEMA}}


@pytest.mark.parametrize("stop_reason, kind", [("refusal", "refused"), ("max_tokens", "truncated")])
def test_anthropic_bad_stop(stop_reason, kind):
    with pytest.raises(LLMError) as e:
        call("m", FakeAnthropic("{}", stop_reason=stop_reason))
    assert e.value.kind == kind


def test_anthropic_connection_error_is_unavailable():
    import anthropic

    exc = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    with pytest.raises(LLMError) as e:
        call("m", FakeAnthropic(exc=exc))
    assert e.value.kind == "unavailable"


# --- OpenAI-compatible adapter (httpx mock transport: tests only) ----------------


def openai_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def chat_response(content, finish_reason="stop", refusal=None):
    return httpx.Response(200, json={"choices": [{
        "finish_reason": finish_reason,
        "message": {"role": "assistant", "content": content, "refusal": refusal},
    }]})


@pytest.fixture
def openai_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test/v1/")
    monkeypatch.setenv("LLM_API_KEY", "k")


def test_openai_sends_strict_schema_and_parses(openai_env):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return chat_response('{"ok": false}')

    assert call("openai:gpt-x", openai_client(handler)) == {"ok": False}
    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    body = seen["body"]
    assert body["model"] == "gpt-x"
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["response_format"]["json_schema"] == {"name": "output", "strict": True, "schema": SCHEMA}


@pytest.mark.parametrize("response, kind", [
    (httpx.Response(401, text="no"), "auth"),
    (httpx.Response(400, text="bad schema"), "bad_request"),
    (httpx.Response(429, text="slow down"), "unavailable"),
    (httpx.Response(503, text="down"), "unavailable"),
    (httpx.Response(200, json={"nope": 1}), "bad_output"),
    (chat_response("{}", finish_reason="length"), "truncated"),
    (chat_response(None, refusal="no"), "refused"),
    (chat_response("not json"), "bad_output"),
    (chat_response("[1]"), "bad_output"),
])
def test_openai_failures_map_to_kinds(openai_env, response, kind):
    with pytest.raises(LLMError) as e:
        call("openai:gpt-x", openai_client(lambda request: response))
    assert e.value.kind == kind


def test_openai_retries_once_on_transient_errors(openai_env):
    responses = iter([httpx.Response(503), chat_response('{"ok": true}')])
    calls = []

    def handler(request):
        calls.append(request)
        return next(responses)

    assert call("openai:gpt-x", openai_client(handler)) == {"ok": True}
    assert len(calls) == 2


@pytest.mark.parametrize("status, attempts", [(429, 2), (503, 2), (400, 1), (401, 1)])
def test_openai_retries_only_transient_statuses(openai_env, status, attempts):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    with pytest.raises(LLMError):
        call("openai:gpt-x", openai_client(handler))
    assert len(calls) == attempts


def schema_rejected():
    """Groq's answer when the generated JSON misses a required field (seen live)."""
    return httpx.Response(400, json={"error": {
        "message": "Generated JSON does not match the expected schema. Error: jsonschema: '/medication' "
                   "does not validate with /properties/medication/required: missing properties: 'value', 'quote'",
        "type": "invalid_request_error",
        "code": "json_validate_failed",
        "failed_generation": "{}",
    }})


def test_schema_rejection_is_sampled_again(openai_env):
    responses = iter([schema_rejected(), chat_response('{"ok": true}')])
    calls = []

    def handler(request):
        calls.append(request)
        return next(responses)

    assert call("openai:gpt-x", openai_client(handler)) == {"ok": True}
    assert len(calls) == 2


def test_repeated_schema_rejection_is_bad_output_not_bad_request(openai_env):
    calls = []

    def handler(request):
        calls.append(request)
        return schema_rejected()

    with pytest.raises(LLMError) as e:
        call("openai:gpt-x", openai_client(handler))
    assert e.value.kind == "bad_output"  # retryable for the caregiver, unlike bad_request
    assert "missing properties" in e.value.detail
    assert len(calls) == 2


def test_other_400s_are_still_bad_request_without_retry(openai_env):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": {"code": "invalid_value", "message": "bad model"}})

    with pytest.raises(LLMError) as e:
        call("openai:gpt-x", openai_client(handler))
    assert e.value.kind == "bad_request"
    assert len(calls) == 1


def test_openai_network_error_is_unavailable(openai_env):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMError) as e:
        call("openai:gpt-x", openai_client(handler))
    assert e.value.kind == "unavailable"


def test_openai_without_key_needs_custom_base_url(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(LLMError) as e:
        call("openai:gpt-x", openai_client(lambda r: chat_response("{}")))
    assert e.value.kind == "config"

    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")  # e.g. Ollama, no key
    assert call("openai:llama3.1:8b", openai_client(lambda r: chat_response('{"ok": true}'))) == {"ok": True}


def test_groq_uses_groq_url_and_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.setenv("LLM_BASE_URL", "http://ignored.test/v1")  # only for openai:
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return chat_response('{"ok": true}')

    assert call("groq:openai/gpt-oss-120b", openai_client(handler)) == {"ok": True}
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert seen["auth"] == "Bearer gk"
    assert seen["body"]["model"] == "openai/gpt-oss-120b"
    assert seen["body"]["response_format"]["json_schema"]["strict"] is True


def test_groq_without_key_is_a_config_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMError) as e:
        call("groq:openai/gpt-oss-120b", openai_client(lambda r: chat_response("{}")))
    assert e.value.kind == "config"


# --- live call (needs LLM_API_KEY and an openai: EXTRACT_MODEL) ------------------------


@pytest.mark.skipif(not (os.environ.get("LLM_API_KEY")
                         and os.environ.get("EXTRACT_MODEL", "").startswith("openai:")),
                    reason="needs LLM_API_KEY and EXTRACT_MODEL=openai:<model>")
def test_live_openai_compatible_call():
    out = complete_json(system="Answer in JSON.", user="Is water wet? ok=true if yes.",
                        schema=SCHEMA, model=os.environ["EXTRACT_MODEL"], max_tokens=200, timeout=20)
    assert isinstance(out.get("ok"), bool)
