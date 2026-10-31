import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import beat_news

ROSTER = [
    ("Patrick Mahomes", "KC", "QB"),
    ("Isiah Pacheco", "KC", "RB"),
    ("Kareem Hunt", "KC", "RB"),
    ("Travis Kelce", "KC", "TE"),
    ("Josh Allen", "BUF", "QB"),
    ("Josh Allen", "JAX", "LB"),                  # same name, other team
    ("Chiefs", "KC", "DST"),
]
NOW = datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def disk_store(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(beat_news, "DISK", tmp_path / "beat.json")


# ------------------------------------------------------------------ classify
def test_classify_availability_and_role():
    assert ("availability", "down") in beat_news.classify("Pacheco is out Sunday")
    assert ("availability", "down") in beat_news.classify("He has been ruled out")
    assert ("availability", "up") in beat_news.classify("Kelce is expected to play")
    assert ("availability", "uncertain") in beat_news.classify("Hunt is questionable, limited in practice")
    assert ("role", "up") in beat_news.classify("Hunt will start and is the lead back")
    assert ("role", "down") in beat_news.classify("Expect a committee, with fewer touches for Pacheco")


def test_not_expected_to_play_is_not_expected_to_play():
    got = beat_news.classify("Kelce is not expected to play")
    assert ("availability", "down") in got
    assert ("availability", "up") not in got


def test_questions_and_plain_chatter_carry_nothing():
    assert beat_news.classify("Is Pacheco out this week?") == []
    assert beat_news.classify("Great practice weather in Kansas City today") == []
    assert beat_news.classify("The offense is out of rhythm") == []        # "out" alone is not a status
    assert beat_news.classify("Pacheco is out on the field early") == []
    assert ("availability", "down") in beat_news.classify("Pacheco is out for the season")


# ------------------------------------------------------------------ players
def test_find_players_full_name_and_unique_last_name():
    assert beat_news.find_players("Isiah Pacheco is out", ROSTER, "KC") == [("Isiah Pacheco", "KC")]
    assert beat_news.find_players("Pacheco is out", ROSTER, "KC") == [("Isiah Pacheco", "KC")]


def test_find_players_stays_on_the_writers_team():
    assert beat_news.find_players("Allen is out", ROSTER, "BUF") == [("Josh Allen", "BUF")]
    assert beat_news.find_players("Allen is out", ROSTER, "KC") == []


def test_ambiguous_last_name_is_not_guessed():
    roster = ROSTER + [("Jerick McKinnon", "KC", "RB"), ("Joe McKinnon", "KC", "WR")]
    assert beat_news.find_players("McKinnon is out", roster, "KC") == []


def test_read_post_assigns_each_clause_to_its_player():
    got = beat_news.read_post("Kelce is expected to play. Pacheco is out; Hunt will start.", ROSTER, "KC")
    key = {(g["player"], g["type"], g["direction"]) for g in got}
    assert key == {("Travis Kelce", "availability", "up"), ("Isiah Pacheco", "availability", "down"),
                   ("Kareem Hunt", "role", "up")}


def test_read_post_uses_the_single_named_player_for_a_bare_clause():
    got = beat_news.read_post("Pacheco update: ruled out", ROSTER, "KC")
    assert [(g["player"], g["direction"]) for g in got] == [("Isiah Pacheco", "down")]


def test_read_post_ignores_defenses_and_unnamed_players():
    assert beat_news.read_post("The Chiefs are expected to play", ROSTER, "KC") == []
    assert beat_news.read_post("Somebody is out", ROSTER, "KC") == []


# ------------------------------------------------------------------ feeds
def test_parse_bluesky_skips_reposts_and_replies():
    payload = {"feed": [
        {"post": {"uri": "at://did:plc:x/app.bsky.feed.post/3abc", "record": {"text": "Pacheco is out", "createdAt": "2026-10-28T17:00:00Z"}}},
        {"post": {"uri": "at://did:plc:x/app.bsky.feed.post/3def", "record": {"text": "RT", "createdAt": "2026-10-28T17:00:00Z"}},
         "reason": {"$type": "app.bsky.feed.defs#reasonRepost"}},
        {"post": {"uri": "at://did:plc:x/app.bsky.feed.post/3ghi",
                  "record": {"text": "a reply", "createdAt": "2026-10-28T17:00:00Z", "reply": {"parent": {}}}}},
    ]}
    posts = beat_news.parse_bluesky(payload, "writer.bsky.social")
    assert [p["text"] for p in posts] == ["Pacheco is out"]
    assert posts[0]["url"] == "https://bsky.app/profile/writer.bsky.social/post/3abc"


RSS = """<?xml version="1.0"?><rss><channel><item><title>Injury report</title>
<link>https://example.com/a</link><pubDate>Wed, 28 Oct 2026 17:00:00 GMT</pubDate>
<description>&lt;p&gt;Kelce is expected to play.&lt;/p&gt;</description></item></channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Update</title>
<link href="https://example.com/b"/><updated>2026-10-28T17:00:00Z</updated><summary>Hunt will start</summary></entry></feed>"""


def test_parse_feed_rss_and_atom():
    rss = beat_news.parse_feed(RSS)
    assert rss[0]["url"] == "https://example.com/a" and "Kelce is expected to play" in rss[0]["text"] and "<p>" not in rss[0]["text"]
    atom = beat_news.parse_feed(ATOM)
    assert atom[0]["url"] == "https://example.com/b" and "Hunt will start" in atom[0]["text"]


def test_parse_feed_refuses_entities_and_garbage():
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'
    assert beat_news.parse_feed(bomb) == []
    assert beat_news.parse_feed("not xml at all") == []


# ------------------------------------------------------------------ collecting
def _post(text, hours_ago=2, pid="p1"):
    return {"id": pid, "text": text, "url": f"https://x/{pid}", "posted_at": NOW - timedelta(hours=hours_ago)}


def test_collect_keeps_recent_posts_and_reports_failed_feeds(monkeypatch):
    writers = [{"name": "Good Writer", "team": "KC", "bluesky": "good.bsky.social", "verified": True},
               {"name": "Down Writer", "team": "KC", "bluesky": "down.bsky.social"}]

    async def fake(client, w):
        if w["name"] == "Down Writer":
            raise RuntimeError("boom")
        return [_post("Pacheco is out"), _post("Kelce is out", hours_ago=24 * 9, pid="old")]

    monkeypatch.setattr(beat_news, "_fetch_writer", fake)
    signals, failed = asyncio.run(beat_news.collect(writers, ROSTER, 2026, 7, now=NOW))
    assert failed == ["Down Writer"]
    assert [(s["player"], s["direction"], s["verified"]) for s in signals] == [("Isiah Pacheco", "down", True)]
    assert signals[0]["url"] == "https://x/p1" and signals[0]["writer"] == "Good Writer"


def test_signal_ids_are_stable_and_storage_is_idempotent(monkeypatch):
    writers = [{"name": "W", "team": "KC", "bluesky": "w.bsky.social"}]

    async def fake(client, w):
        return [_post("Pacheco is out")]

    monkeypatch.setattr(beat_news, "_fetch_writer", fake)
    first, _ = asyncio.run(beat_news.collect(writers, ROSTER, 2026, 7, now=NOW))
    second, _ = asyncio.run(beat_news.collect(writers, ROSTER, 2026, 7, now=NOW + timedelta(minutes=10)))
    assert first[0]["id"] == second[0]["id"]
    assert beat_news.save(first) == 1
    assert beat_news.save(second) == 0
    assert len(beat_news.load(2026, 7)) == 1 and beat_news.load(2026, 8) == []


def test_excerpt_is_capped(monkeypatch):
    writers = [{"name": "W", "team": "KC", "bluesky": "w.bsky.social"}]

    async def fake(client, w):
        return [_post("Pacheco is out. " + "x" * 1000)]

    monkeypatch.setattr(beat_news, "_fetch_writer", fake)
    signals, _ = asyncio.run(beat_news.collect(writers, ROSTER, 2026, 7, now=NOW))
    assert len(signals[0]["text"]) <= beat_news.MAX_EXCERPT


# ------------------------------------------------------------------ how it is used
def _sig(player, kind, direction, writer="W", verified=True, at="2026-10-28T17:00:00+00:00"):
    return {"player": player, "team": "KC", "type": kind, "direction": direction, "writer": writer, "verified": verified,
            "posted_at": at}


def test_ownership_watch_leans_and_mixed():
    rows = [_sig("A", "availability", "down"), _sig("A", "role", "down", writer="W2"),
            _sig("B", "availability", "down"), _sig("B", "availability", "up", writer="W2", verified=False),
            _sig("C", "availability", "uncertain")]
    got = {w["player"]: w for w in beat_news.ownership_watch(rows)}
    assert got["A"]["lean"] == "down" and got["A"]["reports"] == 2 and got["A"]["writers"] == ["W", "W2"]
    assert got["B"]["lean"] == "mixed" and got["B"]["verified_only"] is False
    assert got["C"]["lean"] == "watch"
    assert all(isinstance(w["lean"], str) for w in got.values())          # words, never a number


def test_nothing_is_promoted_by_default():
    assert beat_news.promoted() == set()
    assert json.loads(beat_news.EVIDENCE_FILE.read_text())["promoted"] == []


def test_grade_promotes_only_with_enough_games_and_a_clear_edge():
    kind = ("availability", "up")
    strong = [{"type": kind[0], "direction": kind[1], "hit": i < 54} for i in range(60)]        # 90% vs 72% base
    assert beat_news.grade(strong, {kind: 0.72})["availability|up"]["promote"] is True
    few = strong[:10]
    assert beat_news.grade(few, {kind: 0.5})["availability|up"]["promote"] is False              # n < min_n
    noisy = [{"type": kind[0], "direction": kind[1], "hit": i % 4 != 0} for i in range(60)]     # 75% vs 72% base
    assert beat_news.grade(noisy, {kind: 0.72})["availability|up"]["promote"] is False
    assert beat_news.grade(strong, {})["availability|up"]["promote"] is False                    # no baseline, no promotion


def test_no_writers_means_an_honest_empty_answer(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main
    monkeypatch.setattr(beat_news, "load_writers", lambda: [])
    main._beat_state.clear()
    body = TestClient(main.app).get("/api/beat-news?season=2026&week=7").json()
    assert body["mode"] == "context" and body["signals"] == [] and body["watch"] == []
    assert body["coverage"] == {"writers": 0, "verified": 0, "teams": 0}


def test_discovery_scores_bios_without_trusting_them():
    from scripts.discover_beat_writers import score_actor

    beat = {"displayName": "Pat Reporter", "description": "Chiefs beat writer for The Athletic. Senior reporter."}
    fan = {"displayName": "Chiefs Kingdom", "description": "Chiefs fan account, not affiliated with the NFL"}
    other = {"displayName": "Sam Writer", "description": "Covers the Browns for the Plain Dealer"}
    assert score_actor(beat, "Chiefs") > 0
    assert score_actor(fan, "Chiefs") == 0                  # fan accounts and parodies score nothing
    assert score_actor(other, "Chiefs") == 0                # wrong team
