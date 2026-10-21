import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _api_open_in_tests(monkeypatch):
    """The API needs a signed-in account in production (app.main._require_sign_in);
    tests exercise the endpoints directly. tests/test_main.py checks the gate itself."""
    monkeypatch.setenv("REQUIRE_SIGN_IN", "0")
    monkeypatch.setenv("FOUNDING_PRO", "0")
