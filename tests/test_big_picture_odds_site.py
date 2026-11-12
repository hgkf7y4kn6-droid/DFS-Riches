import asyncio

import pytest

from app.big_picture import odds


class _Resp:
    status_code = 403
    headers = {"content-type": "text/html", "server": "cloudflare"}
    text = "<html>Just a moment...</html>"

    def json(self):
        raise ValueError("not json")


class _Client:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return _Resp()


def test_challenge_page_is_an_ordinary_error(monkeypatch):
    """The research run wraps this optional capture in `except Exception`: a SystemExit (the Nov 7 change) slipped through
    it and killed every Big Picture run behind Cloudflare's challenge page."""
    monkeypatch.setattr(odds.httpx, "AsyncClient", _Client)
    with pytest.raises(Exception) as e:
        asyncio.run(odds.snapshot_via_runner("https://example.test"))
    assert not isinstance(e.value, SystemExit) and "403" in str(e.value) and "cloudflare" in str(e.value)
