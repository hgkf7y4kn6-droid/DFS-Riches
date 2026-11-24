import re
import tempfile
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import guard, main

FORGED_NONE = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJhZG1pbiJ9."          # {"alg":"none"} . {"sub":"admin"} .
# The only routes outside /api/ that exist on purpose; a new one must be added here after a review.
PUBLIC_NON_API = {"/healthz", "/csp-report", "/", "/classic", "/breakdown", "/classic/{rest:path}", "/{path:path}"}


@pytest.fixture
def anon(monkeypatch):
    monkeypatch.setenv("REQUIRE_SIGN_IN", "1")                                   # as in production
    monkeypatch.setattr(guard.RateLimiter, "check", lambda self, client, name, now=None: 0.0)   # a 429 must not hide a 200
    return TestClient(main.app, raise_server_exceptions=False)


def _api_routes():
    for r in main.app.routes:
        if isinstance(r, APIRoute) and r.path.startswith("/api/"):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                yield m, r.path


def test_every_api_route_refuses_anonymous_callers(anon):
    """Anonymous, garbage-token and alg=none-token calls: all 401/403 -- never data, never a 500 that leaks a stack trace."""
    odd = []
    for method, path in _api_routes():
        url = re.sub(r"\{[^}]+\}", "x", path)
        kw = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
        for headers in ({}, {"Authorization": "Bearer not.a.jwt"}, {"Authorization": f"Bearer {FORGED_NONE}"}):
            code = anon.request(method, url, headers=headers, **kw).status_code
            if code not in (401, 403):
                odd.append((method, path, tuple(headers), code))
    assert not odd, f"routes that answered an anonymous caller: {odd}"


def test_the_one_open_api_call_is_the_odds_summary(anon, monkeypatch):
    assert anon.get("/api/odds").status_code == 401                              # without summary=1 it is gated like the rest
    monkeypatch.setenv("ODDS_TRIGGER_SECRET", "s3cret")
    assert anon.get("/api/odds?summary=1").status_code == 401                    # with a secret set, summary needs it too
    assert anon.get("/api/odds?summary=1", headers={"X-Odds-Secret": "wrong"}).status_code == 401


def test_no_unreviewed_public_routes():
    paths = {r.path for r in main.app.routes if not (isinstance(r, APIRoute) and r.path.startswith("/api/"))
             and not r.path.startswith(("/openapi", "/docs", "/redoc"))}
    assert paths <= PUBLIC_NON_API, f"new public route(s) outside /api/: {sorted(paths - PUBLIC_NON_API)}"


def test_web_files_cannot_escape_the_web_directory(monkeypatch):
    root = Path(tempfile.mkdtemp())
    web = root / "web"
    web.mkdir()
    (web / "index.html").write_text("shell")
    (web / "a.js").write_text("x")
    (root / "secret.txt").write_text("TOP SECRET")
    monkeypatch.setattr(main, "WEB_DIR", web)
    assert main._web_file("a.js").name == "a.js"
    for p in ("../secret.txt", "a/../../secret.txt", "..%2fsecret.txt", "/etc/passwd", "....//secret.txt", "\x00", "a\x00.js"):
        f = main._web_file(p)
        assert f.name == "index.html" and f.resolve().is_relative_to(web.resolve()), p


def test_unauthenticated_api_answers_are_not_cacheable(anon):
    r = anon.get("/api/slates")
    assert r.status_code == 401 and r.headers["cache-control"] == "no-store"


def test_csp_report_endpoint_logs_only_and_is_capped(anon):
    main._csp_window.clear()
    codes = [anon.post("/csp-report", content=b"{" + b"x" * 10000).status_code for _ in range(35)]
    assert set(codes) == {204}
    assert len(main._csp_window) == 30                          # 5 reports beyond the cap were dropped
    assert "report-uri /csp-report" in main._csp()
    main._csp_window.clear()


def test_csp_allows_posthog_analytics():
    connect = [d for d in main._csp().split("; ") if d.startswith("connect-src")][0]
    assert "https://us.i.posthog.com" in connect.split()


def test_best_contests_rejects_an_unknown_guaranteed_value(anon, monkeypatch):
    # validation runs before sign-in is consulted only for /api paths that are open; here it must still never be a 500
    assert anon.get("/api/contests/best?guaranteed=maybe").status_code in (401, 403, 422)
