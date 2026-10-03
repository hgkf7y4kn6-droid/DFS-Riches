import pytest
from fastapi.testclient import TestClient

from app import accounts, guard, main


def test_buckets():
    assert guard.bucket("GET", "/cash") is None                       # pages and the web build: unlimited
    assert guard.bucket("GET", "/api/week") == "api"
    assert guard.bucket("GET", "/api/plays") == "heavy"
    assert guard.bucket("GET", "/api/slates/1/ownership") == "heavy"
    assert guard.bucket("PUT", "/api/me/data/settings") == "write"


def test_rate_limit_window_and_per_client():
    rl = guard.RateLimiter()
    limit = guard.LIMITS["write"]
    assert all(rl.check("1.1.1.1", "write", now=100.0) == 0 for _ in range(limit))
    assert rl.check("1.1.1.1", "write", now=100.0) > 0               # over the limit
    assert rl.check("2.2.2.2", "write", now=100.0) == 0               # other clients unaffected
    assert rl.check("1.1.1.1", "write", now=100.0 + guard.WINDOW_SECONDS) == 0   # window slides


def test_tracked_clients_are_bounded(monkeypatch):
    monkeypatch.setattr(guard, "MAX_CLIENTS", 5)
    rl = guard.RateLimiter()
    for i in range(50):
        rl.check(f"10.0.0.{i}", "api", now=1.0)
    assert len(rl._hits) == 5


def test_client_ip_prefers_the_edge_header():
    assert guard.client_ip({"cf-connecting-ip": "9.9.9.9", "x-forwarded-for": "1.1.1.1"}, "127.0.0.1") == "9.9.9.9"
    assert guard.client_ip({"x-forwarded-for": "1.1.1.1, 10.0.0.1"}, "127.0.0.1") == "1.1.1.1"
    assert guard.client_ip({}, "127.0.0.1") == "127.0.0.1"


@pytest.fixture
def client():
    return TestClient(main.app)


def test_middleware_returns_429_then_recovers(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_API", "3")
    headers = {"cf-connecting-ip": "203.0.113.7"}
    codes = [client.get("/api/nope", headers=headers).status_code for _ in range(4)]
    assert codes == [404, 404, 404, 429]
    r = client.get("/api/nope", headers=headers)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert client.get("/api/nope", headers={"cf-connecting-ip": "203.0.113.8"}).status_code == 404


def test_oversized_bodies_are_rejected(client):
    big = "x" * (guard.MAX_BODY_BYTES + 10)
    r = client.post("/api/ownership/duplication", content=big, headers={"content-type": "application/json",
                                                                         "cf-connecting-ip": "203.0.113.20"})
    assert r.status_code == 413


def test_shared_ownership_uploads_need_a_master_account(client, monkeypatch):
    body = {"season": 2026, "week": 4, "slate_id": "1", "source": "x", "text": "a, 1"}
    ip = {"cf-connecting-ip": "203.0.113.30"}
    assert client.post("/api/ownership/source", json=body, headers=ip).status_code == 401

    async def verify(auth):
        return "user_plain"

    async def not_master(uid):
        return False
    monkeypatch.setattr(accounts, "verify", verify)
    monkeypatch.setattr(accounts, "is_master", not_master)
    for ep in ("source", "crowd", "actual"):
        r = client.post(f"/api/ownership/{ep}", json=body, headers={**ip, "authorization": "Bearer t"})
        assert r.status_code == 403
