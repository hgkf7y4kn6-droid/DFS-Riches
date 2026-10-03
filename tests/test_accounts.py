import asyncio
import os
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import accounts

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ISS = f"https://{accounts.frontend_api()}"


def _token(sub="user_abc", exp_in=300, iss=ISS, key=KEY, kid="kid1"):
    now = int(time.time())
    return jwt.encode({"sub": sub, "iss": iss, "iat": now, "exp": now + exp_in}, key, algorithm="RS256",
                      headers={"kid": kid})


@pytest.fixture(autouse=True)
def _jwks(monkeypatch):
    async def signing_key(kid):
        if kid != "kid1":
            raise accounts.AuthError("unknown signing key")
        return KEY.public_key()
    monkeypatch.setattr(accounts, "_signing_key", signing_key)
    for var in ("DATABASE_URL", "CLERK_SECRET_KEY", "MASTER_USER_IDS", "MASTER_EMAILS"):
        monkeypatch.delenv(var, raising=False)
    accounts._USERS.clear()


def test_frontend_api_from_publishable_key():
    assert accounts.frontend_api("pk_test_cmVsYXRlZC1jb3VnYXItMjE5MC5jbGVyay5hY2NvdW50cy5kZXYk") == \
        "related-cougar-2190.clerk.accounts.dev"


def test_verify_accepts_a_valid_session_and_rejects_bad_ones():
    assert asyncio.run(accounts.verify(f"Bearer {_token()}")) == "user_abc"
    for bad in (None, "Basic x", f"Bearer {_token(exp_in=-120)}", f"Bearer {_token(iss='https://evil.example')}",
                f"Bearer {_token(key=rsa.generate_private_key(public_exponent=65537, key_size=2048))}",
                f"Bearer {_token(kid='other')}"):
        with pytest.raises(accounts.AuthError):
            asyncio.run(accounts.verify(bad))


def test_regular_accounts_keep_recent_weeks_masters_keep_everything():
    lineups = {f"2026:{w}:classic": {"savedAt": "x"} for w in range(1, 11)}
    pruned = accounts.prune("saved_lineups", lineups, master=False)
    assert set(pruned) == {f"2026:{w}:classic" for w in range(5, 11)}
    assert accounts.prune("saved_lineups", lineups, master=True) == lineups
    subs = [{"id": i} for i in range(500)]
    assert accounts.prune("submissions", subs, master=False) == subs          # entries are never pruned


def test_validate_rejects_unknown_keys_and_oversized_values():
    with pytest.raises(ValueError):
        accounts.validate("passwords", {}, master=False)
    big = {"x": "a" * (accounts.MAX_BYTES + 10)}
    with pytest.raises(ValueError):
        accounts.validate("settings", big, master=False)
    accounts.validate("settings", big, master=True)                           # masters get more room


def test_master_from_env_or_clerk_role(monkeypatch):
    monkeypatch.setenv("MASTER_USER_IDS", "user_me, user_other")
    assert asyncio.run(accounts.is_master("user_me"))
    monkeypatch.delenv("MASTER_USER_IDS")

    async def user(uid):
        return {"public_metadata": {"role": "master"}} if uid == "user_role" else {}
    monkeypatch.setattr(accounts, "clerk_user", user)
    assert asyncio.run(accounts.is_master("user_role"))
    assert not asyncio.run(accounts.is_master("user_plain"))


def test_master_by_verified_email(monkeypatch):
    monkeypatch.setenv("MASTER_EMAILS", "Owner@Example.com")

    async def user(uid):
        status = "verified" if uid == "user_owner" else "unverified"
        return {"email_addresses": [{"email_address": "owner@example.com", "verification": {"status": status}}]}
    monkeypatch.setattr(accounts, "clerk_user", user)
    assert asyncio.run(accounts.is_master("user_owner"))
    assert not asyncio.run(accounts.is_master("user_squatter"))      # same address, not verified


def test_no_storage_configured_is_reported():
    assert accounts.storage_mode() == "none"
    with pytest.raises(RuntimeError):
        asyncio.run(accounts.save("user_abc", "settings", {"a": 1}, None))


PG_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not PG_URL, reason="set TEST_DATABASE_URL to run against Postgres")
def test_neon_store_round_trip_last_write_wins_and_profile(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    accounts._SCHEMA_READY["done"] = False
    profiles = []

    async def meta_write(uid, data, profile):
        profiles.append(profile)
    monkeypatch.setattr(accounts, "_meta_write", meta_write)

    async def run():
        conn = await accounts._connect()
        async with conn:
            await conn.execute("delete from user_data where user_id like 'test_%'")
        await accounts.save("test_u1", "submissions", [{"id": "a"}], "2026-10-03T10:00:00Z")
        newer = await accounts.save("test_u1", "submissions", [{"id": "a"}, {"id": "b"}], "2026-10-03T11:00:00Z")
        assert len(newer["value"]) == 2
        stale = await accounts.save("test_u1", "submissions", [], "2026-10-03T09:00:00Z")   # older write loses
        assert len(stale["value"]) == 2
        await accounts.save("test_u1", "settings", {"matchup_mode": "adj"}, "2026-10-03T11:00:00Z")
        data = await accounts.load("test_u1")
        assert data["storage"] == "neon" and not data["master"]
        assert data["data"]["settings"]["value"] == {"matchup_mode": "adj"}
        assert (await accounts.load("test_u2"))["data"] == {}                                 # users are isolated
    asyncio.run(run())
    assert profiles[-1]["counts"] == {"submissions": 2, "settings": 1}


def test_clerk_metadata_store_compacts_to_fit(monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_dummy")
    store = {}

    async def meta_load(uid):
        return store.get(uid, {})

    async def meta_write(uid, data, profile):
        store[uid] = data

    async def master(uid):
        return False
    monkeypatch.setattr(accounts, "_meta_load", meta_load)
    monkeypatch.setattr(accounts, "_meta_write", meta_write)
    monkeypatch.setattr(accounts, "is_master", master)
    subs = [{"id": str(i), "contest": "x" * 100} for i in range(200)]
    asyncio.run(accounts.save("u", "submissions", subs, "2026-10-03T10:00:00Z"))
    lineups = {f"2026:{w}:classic": {"lineups": [[1, 2, 3]]} for w in (3, 4)}
    asyncio.run(accounts.save("u", "saved_lineups", lineups, "2026-10-03T10:00:00Z"))
    import json
    assert len(json.dumps(store["u"])) <= accounts.METADATA_BUDGET
    assert list(store["u"]["saved_lineups"]["value"]) == ["2026:4:classic"]          # latest week only
    assert store["u"]["submissions"]["value"][0]["id"] == "0"                         # newest kept


def test_config_status_reports_presence_never_values(monkeypatch):
    assert accounts.config_status() == {"clerk_secret_key": False, "database_url": False, "master_emails": False,
                                        "storage": "none"}
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_secret_value")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host/db")
    status = accounts.config_status()
    assert status["clerk_secret_key"] and status["database_url"] and status["storage"] == "neon"
    assert "sk_test_secret_value" not in str(status) and "pw@host" not in str(status)
