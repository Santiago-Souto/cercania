"""One schema-constrained JSON call to whichever LLM vendor is configured.

Callers pass a model spec "<provider>:<model>":
- "anthropic:claude-haiku-5-5" (a bare model name also means Anthropic);
- "openai:<model>" for any OpenAI-compatible chat/completions endpoint (OpenAI,
  Groq, Gemini's compat endpoint, OpenRouter, Ollama, vLLM), configured with
  LLM_BASE_URL and LLM_API_KEY.

Every vendor failure becomes an LLMError with a vendor-neutral `kind`, so callers
decide what to tell the user without knowing which vendor ran. Callers must still
validate the returned object: a vendor may not enforce the schema strictly.
"""

from __future__ import annotations

import json
import os

import httpx

# Env var holding the API key for each provider.
API_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "LLM_API_KEY"}
PROVIDERS = tuple(API_KEY_ENV)
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class LLMError(Exception):
    """kind: config | auth | bad_request | unavailable | refused | truncated | bad_output."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


def parse_model(spec: str) -> tuple[str, str]:
    """Split a model spec, e.g. "openai:llama3.1:8b" -> ("openai", "llama3.1:8b").

    A bare name or unknown prefix means Anthropic: "claude-haiku-5-5" -> ("anthropic", ...).
    """
    provider, sep, name = spec.partition(":")
    if sep and provider in PROVIDERS and name:
        return provider, name
    return "anthropic", spec


def complete_json(*, system: str, user: str, schema: dict, model: str, max_tokens: int,
                  timeout: float, effort: str | None = None, client=None) -> dict:
    """Return the model's JSON object for `schema`. Raises LLMError on any failure.

    `effort` is a hint only Anthropic honors. `client` is for tests: an Anthropic
    client or an httpx.Client, depending on the provider.
    """
    provider, name = parse_model(model)
    if provider == "openai":
        text = _openai(system, user, schema, name, max_tokens, timeout, client)
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
        try:
            client = anthropic.Anthropic(timeout=timeout, max_retries=1)
        except anthropic.AnthropicError as e:
            raise LLMError("config", "ANTHROPIC_API_KEY is not set") from e
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


# --- OpenAI-compatible --------------------------------------------------------------


def _openai(system, user, schema, name, max_tokens, timeout, client) -> str | None:
    base_url = (os.environ.get("LLM_BASE_URL") or OPENAI_DEFAULT_BASE_URL).rstrip("/")
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key and base_url == OPENAI_DEFAULT_BASE_URL:
        raise LLMError("config", "LLM_API_KEY is not set")  # local servers may not need one
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
    try:
        if client is None:
            with httpx.Client(timeout=timeout) as c:
                response = c.post(f"{base_url}/chat/completions", json=body, headers=headers)
        else:
            response = client.post(f"{base_url}/chat/completions", json=body, headers=headers)
    except httpx.HTTPError as e:
        raise LLMError("unavailable", str(e)) from e

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
