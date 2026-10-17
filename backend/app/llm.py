"""One schema-constrained JSON call to whichever LLM vendor is configured.

Callers pass a model spec "<provider>:<model>":
- "groq:openai/gpt-oss-120b": Groq, with GROQ_API_KEY (the same key as transcription);
- "anthropic:claude-haiku-5-5" (a bare model name also means Anthropic);
- "openai:<model>" for any other OpenAI-compatible chat/completions endpoint
  (OpenAI, xAI, Gemini's compat endpoint, OpenRouter, Ollama, vLLM), configured
  with LLM_BASE_URL and LLM_API_KEY.

Every vendor failure becomes an LLMError with a vendor-neutral `kind`, so callers
decide what to tell the user without knowing which vendor ran. Callers must still
validate the returned object: a vendor may not enforce the schema strictly.
"""

from __future__ import annotations

import json
import os
import time

import httpx

# Env var holding the API key for each provider.
API_KEY_ENV = {"groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "LLM_API_KEY"}
PROVIDERS = tuple(API_KEY_ENV)
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
RETRY_DELAY_SEC = 0.5  # one retry on transient errors, like the Anthropic SDK with max_retries=1


class LLMError(Exception):
    """kind: config | auth | bad_request | unavailable | refused | truncated | bad_output."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


def parse_model(spec: str) -> tuple[str, str]:
    """Split a model spec, e.g. "openai:llama3.1:8b" -> ("openai", "llama3.1:8b").

    A bare name (no colon) means Anthropic: "claude-haiku-5-5" -> ("anthropic", ...).
    An unknown prefix ("grok:grok-4") raises LLMError("config") instead of being
    sent to Anthropic as a model name.
    """
    provider, sep, name = spec.partition(":")
    if not sep:
        return "anthropic", spec
    if provider not in PROVIDERS or not name:
        raise LLMError("config", f"bad model spec {spec!r}; use <provider>:<model> with one of {PROVIDERS}")
    return provider, name


def complete_json(*, system: str, user: str, schema: dict, model: str, max_tokens: int,
                  timeout: float, effort: str | None = None, client=None) -> dict:
    """Return the model's JSON object for `schema`. Raises LLMError on any failure.

    `effort` is a hint only Anthropic honors. `client` is for tests: an Anthropic
    client or an httpx.Client, depending on the provider.
    """
    provider, name = parse_model(model)
    if provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise LLMError("config", "GROQ_API_KEY is not set")
        text = _openai(system, user, schema, name, max_tokens, timeout, client, GROQ_BASE_URL, api_key)
    elif provider == "openai":
        base_url = (os.environ.get("LLM_BASE_URL") or OPENAI_DEFAULT_BASE_URL).rstrip("/")
        api_key = os.environ.get("LLM_API_KEY")
        if not api_key and base_url == OPENAI_DEFAULT_BASE_URL:
            raise LLMError("config", "LLM_API_KEY is not set")  # local servers may not need one
        text = _openai(system, user, schema, name, max_tokens, timeout, client, base_url, api_key)
    else:
        text = _anthropic(system, user, schema, name, max_tokens, timeout, effort, client)
    try:
        raw = json.loads(text or "")
    except json.JSONDecodeError as e:
        raise LLMError("bad_output", "invalid JSON") from e
    if not isinstance(raw, dict):
        raise LLMError("bad_output", f"expected an object, got {type(raw).__name__}")
    return raw


# --- Anthropic ----------------------------------------------------------------------


def _anthropic(system, user, schema, name, max_tokens, timeout, effort, client) -> str | None:
    import anthropic

    if client is None:
        # The SDK only notices a missing key at request time, as a bare TypeError.
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise LLMError("config", "ANTHROPIC_API_KEY is not set")
        client = anthropic.Anthropic(timeout=timeout, max_retries=1)
    output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
    if effort:
        output_config["effort"] = effort
    try:
        response = client.messages.create(
            model=name,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise LLMError("auth", str(e)) from e
    except (anthropic.BadRequestError, anthropic.NotFoundError) as e:
        raise LLMError("bad_request", str(e)) from e
    except (anthropic.RateLimitError, anthropic.APITimeoutError, anthropic.APIConnectionError,
            anthropic.InternalServerError, anthropic.APIStatusError) as e:
        raise LLMError("unavailable", str(e)) from e

    if response.stop_reason == "refusal":
        raise LLMError("refused")
    if response.stop_reason == "max_tokens":
        raise LLMError("truncated")
    return next((b.text for b in response.content if b.type == "text"), None)


# --- OpenAI-compatible (Groq, OpenAI, xAI, ...) -------------------------------------


def _openai(system, user, schema, name, max_tokens, timeout, client, base_url, api_key) -> str | None:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    body = {
        "model": name,
        "max_completion_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "output", "strict": True, "schema": schema},
        },
    }
    url = f"{base_url}/chat/completions"
    own_client = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        for attempt in range(2):
            try:
                response = client.post(url, json=body, headers=headers)
            except httpx.HTTPError as e:
                if attempt:
                    raise LLMError("unavailable", str(e)) from e
            else:
                transient = response.status_code == 429 or response.status_code >= 500
                if attempt or not transient:
                    break
            time.sleep(RETRY_DELAY_SEC)
    finally:
        if own_client:
            client.close()

    status = response.status_code
    if status in (401, 403):
        raise LLMError("auth", response.text[:200])
    if status in (400, 404, 422):
        raise LLMError("bad_request", response.text[:200])
    if status >= 300:
        raise LLMError("unavailable", f"HTTP {status}: {response.text[:200]}")

    try:
        choice = response.json()["choices"][0]
        message = choice["message"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise LLMError("bad_output", "unexpected response shape") from e
    if choice.get("finish_reason") == "length":
        raise LLMError("truncated")
    if message.get("refusal") or choice.get("finish_reason") == "content_filter":
        raise LLMError("refused")
    content = message.get("content")
    return content if isinstance(content, str) else None
