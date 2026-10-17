import pytest

from app import whatsapp


@pytest.fixture(autouse=True)
def whatsapp_env(monkeypatch):
    """Fake credentials so no test can reach Meta or Groq with real ones."""
    monkeypatch.setenv("WHATSAPP_TOKEN", "test-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "1111")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-me")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "app-secret")
    monkeypatch.setenv("GROQ_API_KEY", "groq-test")
    monkeypatch.setattr(whatsapp, "seen_messages", whatsapp.SeenMessages())
