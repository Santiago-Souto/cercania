import os

import pytest

# main.py reads WEB_ORIGINS once, at import; pin it before any test imports the app.
# (.env never overrides it: models.py loads it with override=False.)
os.environ["WEB_ORIGINS"] = "http://localhost:3000"


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
def fake_env(request, monkeypatch):
    """Fake credentials so no test can reach Groq with real ones.

    Tests marked `live` keep the real GROQ_API_KEY: they decide to run because
    that key exists, so replacing it would make them fail with "Invalid API Key".
    """
    if request.node.get_closest_marker("live") is None:
        monkeypatch.setenv("GROQ_API_KEY", "groq-test")
    # Never reach the real Supabase bucket from a test; storage tests set fake values.
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    # A developer's .env (loaded by models.py) must not change auth behavior under test;
    # tests that need these set them themselves.
    for var in ("AUTH_DEV_LOG_CODES", "SESSION_COOKIE_SECURE", "SESSION_COOKIE_SAMESITE"):
        monkeypatch.delenv(var, raising=False)
