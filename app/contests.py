"""Best contests: the cheapest-to-play NFL GPPs in DraftKings' lobby.

Two public (unauthenticated, undocumented) DraftKings endpoints:
  - GET www.draftkings.com/lobby/getcontests?sport=NFL
        Every upcoming NFL contest: entry fee "a", field size "m", prize pool
        "po", max entries per user "mec", payout template "tmpl", gameType and
        attr flags (IsDoubleUp, League, Multiplier, ...). Rake is 1 - po / (a * m).
  - GET api.draftkings.com/contests/v1/contests/{id}
        One contest's payout table (payoutSummary). Contests built from the
        same template share it, so it's fetched once per template and gives
        the share of the field that gets paid.

GPPs here are salary-cap Classic and Showdown tournaments on any slate (main,
early, Sun-Mon, full-week Thu-Mon, single-game Showdown), including boosters
(multipliers), leagues and qualifiers (ticket and seat prizes count at face
value, as DraftKings' prize pool does); no double-ups / 50-50s (cash games),
head-to-heads or free contests. They're grouped by max entries per user and
entry fee; each group lists its 15 lowest-rake contests, ties broken by the
larger share of the field paid.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

from app.cache import cached_fetch
from app.config import DK_BASE
from app.dk_client import _get_json

LOBBY_URL = "https://www.draftkings.com/lobby/getcontests?sport=NFL"
TTL_LOBBY = 60 * 10
TTL_PAYOUTS = 60 * 60 * 12  # a template's payout table doesn't change

GPP_GAME_TYPES = {"Classic", "Showdown Captain Mode"}
NOT_GPP_ATTRS = {"IsDoubleUp", "IsFiftyfifty"}
# Shown on each row: (attr flag, label), first match wins.
KINDS = [("IsQualifier", "Qualifier"), ("Multiplier", "Booster"), ("League", "League")]
TOP_N = 15
# Lowest-rake contests per group whose payout tables are looked up: enough to
# rank the top 15 by share paid among the ones tied on rake.
CANDIDATES = 40
PAYOUT_CONCURRENCY = 8

# (id, label, lowest, highest max entries per user)
ENTRY_GROUPS = [
    ("se", "Single entry", 1, 1),
    ("2-10", "2–10 max", 2, 10),
    ("20", "20 max", 11, 20),
    ("150", "150 max", 21, 150),
]
# (id, label, lowest fee inclusive, highest fee exclusive)
FEE_GROUPS = [
    ("under1", "Under $1", 0.0, 1.0),
    ("1-4", "$1–$4", 1.0, 5.0),
    ("5-9", "$5–$9", 5.0, 10.0),
    ("10-25", "$10–$25", 10.0, 25.01),
    ("over25", "Over $25", 25.01, float("inf")),
]

_DATE_RE = re.compile(r"/Date\((\d+)\)/")


def _start_utc(value: str | None) -> str | None:
    m = _DATE_RE.match(value or "")
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).isoformat() if m else None


def is_gpp(c: dict) -> bool:
    return (
        c.get("gameType") in GPP_GAME_TYPES
        and not NOT_GPP_ATTRS & set(c.get("attr") or {})
        and (c.get("m") or 0) > 2
        and (c.get("a") or 0) > 0
        and (c.get("po") or 0) > 0
    )


def entry_group(max_entries: int) -> str | None:
    return next((gid for gid, _, lo, hi in ENTRY_GROUPS if lo <= max_entries <= hi), None)


def fee_group(fee: float) -> str | None:
    return next((gid for gid, _, lo, hi in FEE_GROUPS if lo <= fee < hi), None)


def _kind(attr: dict) -> str:
    return next((label for flag, label in KINDS if flag in attr), "Tournament")


def _slate(group: dict | None, game_type: str | None) -> str:
    """The draft group's slate, e.g. "Main", "Thu-Mon", "Early Only", "SEA @ DEN"."""
    suffix = ((group or {}).get("ContestStartTimeSuffix") or "").strip(" ()")
    return suffix or ("Main" if game_type == "Classic" else "")


def _row(c: dict, groups: dict[int, dict] | None = None) -> dict:
    fee, size, pool = float(c["a"]), int(c["m"]), float(c["po"])
    return {
        "id": c["id"],
        "name": (c.get("n") or "").strip(),
        "game_type": c.get("gameType"),
        "entry_fee": fee,
        "max_entries": int(c.get("mec") or 1),
        "field_size": size,
        "entries": int(c.get("nt") or 0),
        "prize_pool": pool,
        "rake": round(1 - pool / (fee * size), 4),
        "guaranteed": (c.get("attr") or {}).get("IsGuaranteed") == "true",
        "kind": _kind(c.get("attr") or {}),
        "slate": _slate((groups or {}).get(c.get("dg")), c.get("gameType")),
        "start_utc": _start_utc(c.get("sd")),
        "start_label": c.get("sdstring") or "",
        "draft_group_id": c.get("dg"),
        "template_id": c.get("tmpl"),
        "paid_places": None,
        "paid_pct": None,
    }


def is_free_cash(c: dict) -> bool:
    """A free contest whose prizes include cash (not only tickets or crowns)."""
    return (c.get("a") or 0) == 0 and (c.get("po") or 0) > 0 and "Cash" in (c.get("pd") or {})


def _free_row(c: dict, groups: dict[int, dict]) -> dict:
    return {
        "id": c["id"],
        "name": (c.get("n") or "").strip(),
        "game_type": c.get("gameType"),
        "prize_pool": float(c["po"]),
        "cash": (c.get("pd") or {}).get("Cash"),
        "field_size": int(c.get("m") or 0),
        "entries": int(c.get("nt") or 0),
        "max_entries": int(c.get("mec") or 1),
        "slate": _slate(groups.get(c.get("dg")), c.get("gameType")),
        "start_utc": _start_utc(c.get("sd")),
    }


async def _lobby() -> dict[str, list[dict]]:
    """The lobby trimmed to what the cards use: {"gpps": [...], "free": [...]}."""
    async def fetch() -> dict[str, list[dict]]:
        data = await _get_json(LOBBY_URL)
        groups = {g.get("DraftGroupId"): g for g in data.get("DraftGroups") or []}
        lobby = data.get("Contests", [])
        return {
            "gpps": [_row(c, groups) for c in lobby if is_gpp(c)],
            "free": [_free_row(c, groups) for c in lobby if is_free_cash(c)],
        }

    return await cached_fetch("dk_lobby_nfl_v3", TTL_LOBBY, fetch)


async def free_contests() -> dict[str, Any]:
    """Free NFL contests that pay cash, soonest first."""
    rows = sorted((await _lobby())["free"], key=lambda r: (r["start_utc"] or "", -r["prize_pool"]))
    return {"contests": rows, "updated_at": datetime.now(timezone.utc).isoformat()}


def paid_places(detail: dict) -> int | None:
    """The last paid finishing position in a contest's payout table."""
    tiers = (detail.get("contestDetail") or {}).get("payoutSummary") or []
    places = [t.get("maxPosition") or 0 for t in tiers]
    return max(places) if places else None


async def _paid_places(contest_id: int, template_id: int, sem: asyncio.Semaphore) -> int | None:
    async def fetch() -> dict:
        async with sem:
            detail = await _get_json(f"{DK_BASE}/contests/v1/contests/{contest_id}?format=json")
        return {"paid_places": paid_places(detail)}

    try:
        return (await cached_fetch(f"dk_payout_tmpl_{template_id}", TTL_PAYOUTS, fetch))["paid_places"]
    except Exception:
        return None  # ranked on rake alone


def _rank_key(r: dict) -> tuple:
    # Rake to the tenth of a percent, then share of field paid, then the bigger pool.
    return (round(r["rake"], 3), -(r["paid_pct"] or 0), -r["prize_pool"])


def group_contests(rows: list[dict]) -> dict[str, dict[str, list[dict]]]:
    groups: dict[str, dict[str, list[dict]]] = {e[0]: {f[0]: [] for f in FEE_GROUPS} for e in ENTRY_GROUPS}
    for r in rows:
        eg, fg = entry_group(r["max_entries"]), fee_group(r["entry_fee"])
        if eg and fg:
            groups[eg][fg].append(r)
    return groups


async def best_contests() -> dict[str, Any]:
    groups = group_contests((await _lobby())["gpps"])

    # Payout tables for each group's lowest-rake candidates, one fetch per template.
    candidates = {
        eg: {fg: sorted(rows, key=lambda r: (r["rake"], -r["prize_pool"]))[:CANDIDATES] for fg, rows in fees.items()}
        for eg, fees in groups.items()
    }
    templates = {r["template_id"]: r["id"] for fees in candidates.values() for rows in fees.values() for r in rows}
    sem = asyncio.Semaphore(PAYOUT_CONCURRENCY)
    paid = dict(zip(templates, await asyncio.gather(*(_paid_places(cid, t, sem) for t, cid in templates.items()))))

    out: dict[str, dict[str, list[dict]]] = {}
    for eg, fees in candidates.items():
        out[eg] = {}
        for fg, rows in fees.items():
            ranked = []
            for r in rows:
                places = paid.get(r["template_id"])
                ranked.append({**r, "paid_places": places,
                               "paid_pct": round(min(places / r["field_size"], 1.0), 4) if places else None})
            out[eg][fg] = sorted(ranked, key=_rank_key)[:TOP_N]
    return {
        "entry_groups": [{"id": gid, "label": label, "min": lo, "max": hi} for gid, label, lo, hi in ENTRY_GROUPS],
        "fee_groups": [{"id": gid, "label": label} for gid, label, _, _ in FEE_GROUPS],
        "contests": out,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
