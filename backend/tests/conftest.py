import os

import pytest

# main.py reads WEB_ORIGINS once, at import; pin it before any test imports the app.
# (.env never overrides it: models.py loads it with override=False.)
os.environ["WEB_ORIGINS"] = "http://localhost:3000"

from app import whatsapp  # noqa: E402


def pytest_collection_modifyitems(config, items):
    """Live tests spend real quota (Groq's free tier allows ~2 extractions per
    minute) and depend on the network, so they run only when asked for."""
    if os.environ.get("RUN_LIVE_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set RUN_LIVE_TESTS=1 to run it")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def whatsapp_env(request, monkeypatch):
    """Fake credentials so no test can reach Meta or Groq with real ones.

    Tests marked `live` keep the real GROQ_API_KEY: they decide to run because
    that key exists, so replacing it would make them fail with "Invalid API Key".
    """
    monkeypatch.setenv("WHATSAPP_TOKEN", "test-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "1111")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-me")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "app-secret")
    if request.node.get_closest_marker("live") is None:
        monkeypatch.setenv("GROQ_API_KEY", "groq-test")
    monkeypatch.setattr(whatsapp, "seen_messages", whatsapp.SeenMessages())
