import importlib

from fastapi.testclient import TestClient


def _reload(monkeypatch, value):
    from app import main
    if value is None:
        monkeypatch.delenv("ENABLE_API_DOCS", raising=False)
    else:
        monkeypatch.setenv("ENABLE_API_DOCS", value)
    return importlib.reload(main)


def test_api_docs_are_off_by_default(monkeypatch):
    """/docs, /redoc and /openapi.json are outside /api/, so sign-in never covered them: they listed every route."""
    m = _reload(monkeypatch, None)
    try:
        c = TestClient(m.app)
        assert c.get("/openapi.json").status_code != 200
        assert "swagger" not in c.get("/docs").text.lower()
        assert "redoc" not in c.get("/redoc").text.lower()
    finally:
        _reload(monkeypatch, None)


def test_api_docs_can_be_enabled_for_development(monkeypatch):
    m = _reload(monkeypatch, "1")
    try:
        assert TestClient(m.app).get("/openapi.json").status_code == 200
    finally:
        _reload(monkeypatch, None)
