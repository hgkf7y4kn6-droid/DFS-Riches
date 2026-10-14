"""Best contests: the cheapest-to-play NFL GPPs in DraftKings' lobby.

Two public (unauthenticated, undocumented) DraftKings endpoints:
  - GET www.draftkings.com/lobby/getcontests?sport=NFL
        Every upcoming NFL contest: entry fee "a", field size "m", prize pool
        "po", max entries per user "mec", payout template "tmpl", gameType and
        attr flags (IsDoubleUp, League, Multiplier, ...). Rake is 1 - po / (a * m).
  - GET api.draftkings.com/contests/v1/contests/{id}
        One contest's payout table (payoutSummary). Contests built from the
        same template share it, so it's fetched once per template and gives
        the share of the field that gets paid and the first-place prize.

GPPs here are salary-cap Classic and Showdown tournaments on any slate (main,
early, Sun-Mon, full-week Thu-Mon, single-game Showdown), including boosters
(multipliers), leagues and qualifiers (ticket and seat prizes count at face
value, as DraftKings' prize pool does); no double-ups / 50-50s (cash games),
head-to-heads, free contests, or Beginner / Casual contests (closed to
experienced players). The user picks any mix of max-entries groups, fee groups
and kinds; the 15 best of those are listed, scored with the user's weights on
low rake, share of the field paid, first prize for the fee and field size.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
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
# Beginner and Casual contests: only newer / less experienced players can enter.
RESTRICTED_ATTRS = {"IsBeginner", "IsCasual"}
# Shown on each row: (attr flag, label), first match wins.
KINDS = [("IsQualifier", "Qualifier"), ("Multiplier", "Booster"), ("League", "League")]
CONTEST_KINDS = ["Tournament", "Booster", "League", "Qualifier"]
TOP_N = 15
PAYOUT_CONCURRENCY = 8
# How much each percentile counts in a contest's score (score_contests), in points the user
# can set from 0 to MAX_WEIGHT; each counts for its share of the total. Field size starts off.
WEIGHTS = {"rake": 4, "paid": 3, "payout": 3, "field": 0}
MAX_WEIGHT = 10

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
    ("1-5", "$1–$5", 1.0, 5.01),
    ("6-10", "$6–$10", 5.01, 10.01),
    ("11-25", "$11–$25", 10.01, 25.01),
    ("over25", "Over $25", 25.01, float("inf")),
]

_DATE_RE = re.compile(r"/Date\((\d+)\)/")


def _start_utc(value: str | None) -> str | None:
    m = _DATE_RE.match(value or "")
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).isoformat() if m else None


def is_gpp(c: dict) -> bool:
    return (
        c.get("gameType") in GPP_GAME_TYPES
        and not (NOT_GPP_ATTRS | RESTRICTED_ATTRS) & set(c.get("attr") or {})
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
    return ((c.get("a") or 0) == 0 and (c.get("po") or 0) > 0 and "Cash" in (c.get("pd") or {})
            and not RESTRICTED_ATTRS & set(c.get("attr") or {}))


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

    return await cached_fetch("dk_lobby_nfl_v4", TTL_LOBBY, fetch)


async def free_contests() -> dict[str, Any]:
    """Free NFL contests that pay cash, soonest first."""
    rows = sorted((await _lobby())["free"], key=lambda r: (r["start_utc"] or "", -r["prize_pool"]))
    return {"contests": rows, "updated_at": datetime.now(timezone.utc).isoformat()}


def payout_summary(detail: dict) -> dict:
    """The last paid finishing position and the first-place prize (cash plus tickets or
    seats at face value) from a contest's payout table."""
    tiers = (detail.get("contestDetail") or {}).get("payoutSummary") or []
    places = [t.get("maxPosition") or 0 for t in tiers]
    first = next((t for t in tiers if t.get("minPosition") == 1), None)
    top = sum(p.get("value") or 0 for p in (first or {}).get("payoutDescriptions") or [])
    return {"paid_places": max(places) if places else None, "top_prize": float(top) if top else None}


# Payout tables by template id: (fetched at, summary). Kept here rather than in
# app.cache's small LRU, since a ranking reads hundreds of them.
_PAYOUTS: dict[int, tuple[float, dict]] = {}


async def _payout(contest_id: int, template_id: int, sem: asyncio.Semaphore) -> dict:
    hit = _PAYOUTS.get(template_id)
    if hit and time.time() - hit[0] < TTL_PAYOUTS:
        return hit[1]

    async def fetch() -> dict:
        async with sem:
            detail = await _get_json(f"{DK_BASE}/contests/v1/contests/{contest_id}?format=json")
        return payout_summary(detail)

    try:
        summary = await cached_fetch(f"dk_payout_v2_tmpl_{template_id}", TTL_PAYOUTS, fetch, memory=False)
    except Exception:
        return {"paid_places": None, "top_prize": None}  # ranked as the worst on these two
    _PAYOUTS[template_id] = (time.time(), summary)
    return summary


async def _with_payouts(rows: list[dict]) -> list[dict]:
    templates = {r["template_id"]: r["id"] for r in rows}
    sem = asyncio.Semaphore(PAYOUT_CONCURRENCY)
    found = dict(zip(templates, await asyncio.gather(*(_payout(cid, t, sem) for t, cid in templates.items()))))
    out = []
    for r in rows:
        p = found[r["template_id"]]
        places, top = p["paid_places"], p["top_prize"]
        out.append({**r, "paid_places": places, "top_prize": top,
                    "paid_pct": round(min(places / r["field_size"], 1.0), 4) if places else None,
                    "top_multiple": round(top / r["entry_fee"], 1) if top else None})
    return out


def _pct_ranks(values: list[float]) -> list[float]:
    """Each value's percentile (0-1) among values, higher = better; ties share their average rank."""
    if len(values) < 2:
        return [1.0] * len(values)
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 / (len(values) - 1)
        i = j + 1
    return ranks


def normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    """Each factor's share (0-1) of the user's points; WEIGHTS when none are given or all are 0."""
    points = {k: max(0.0, float((weights or {}).get(k, 0))) for k in WEIGHTS}
    if not any(points.values()):
        points = {k: float(v) for k, v in WEIGHTS.items()}
    total = sum(points.values())
    return {k: v / total for k, v in points.items()}


def score_contests(rows: list[dict], weights: dict[str, float] | None = None) -> list[dict]:
    """Ranks contests on low rake, a big share of the field paid, a big first-place prize
    for the entry fee and a small field, each as a percentile among these contests, weighted
    by weights (points per factor; WEIGHTS by default). Score is 0-100; ties go to the lower rake."""
    if not rows:
        return []
    shares = normalize_weights(weights)
    metrics = {
        "rake": [-r["rake"] for r in rows],
        "paid": [r["paid_pct"] or 0.0 for r in rows],
        "payout": [math.log10(r["top_multiple"]) if r["top_multiple"] else 0.0 for r in rows],
        "field": [-r["field_size"] for r in rows],
    }
    ranks = {k: _pct_ranks(v) for k, v in metrics.items() if shares[k]}
    scored = [{**r, "score": round(100 * sum(shares[k] * ranks[k][i] for k in ranks), 1)}
              for i, r in enumerate(rows)]
    return sorted(scored, key=lambda r: (-r["score"], r["rake"], -r["prize_pool"]))


def select(rows: list[dict], entries: frozenset[str], fees: frozenset[str], exclude: frozenset[str]) -> list[dict]:
    """GPPs in the chosen max-entries and fee groups (empty = all), minus excluded kinds."""
    return [r for r in rows
            if r["kind"] not in exclude
            and (eg := entry_group(r["max_entries"])) and (not entries or eg in entries)
            and (fg := fee_group(r["entry_fee"])) and (not fees or fg in fees)]


def base_name(row: dict) -> str:
    """The contest's name without its slate, e.g. "NFL Showdown Satellite to $20 ... (SEA @ DEN)"
    -> "NFL Showdown Satellite to $20 ..."."""
    suffix = f" ({row['slate']})"
    name = row["name"]
    return name[: -len(suffix)] if row["slate"] and name.endswith(suffix) else name


def collapse_copies(rows: list[dict]) -> list[dict]:
    """DraftKings lists many copies of some contests: the same contest (name, fee, field, prize
    pool and payouts -- template ids can differ) repeated on one slate and offered again on others. Keeps one row per
    contest -- the fullest copy, so the closest to running -- with "copies" counting them all and
    "slates" naming every slate it's on, soonest first."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        key = (base_name(r), r["entry_fee"], r["field_size"], r["prize_pool"], r.get("paid_places"), r.get("top_prize"))
        groups.setdefault(key, []).append(r)
    out = []
    for g in groups.values():
        slates = list(dict.fromkeys(r["slate"] for r in sorted(g, key=lambda r: (r["start_utc"] or "", r["slate"]))))
        best = max(g, key=lambda r: r["entries"])
        out.append({**best, "title": base_name(best) if len(slates) > 1 else best["name"],
                    "copies": len(g), "slates": slates})
    return out


async def warm_payouts() -> None:
    """Fetches every listed GPP's payout table so the first ranking doesn't wait on them."""
    try:
        await _with_payouts((await _lobby())["gpps"])
    except Exception:
        pass


async def best_contests(entries: frozenset[str] = frozenset(), fees: frozenset[str] = frozenset(),
                        exclude: frozenset[str] = frozenset(), weights: dict[str, float] | None = None) -> dict[str, Any]:
    """The TOP_N best GPPs (score_contests, with the user's weights) across the chosen
    max-entries groups, fee groups and contest kinds."""
    rows = collapse_copies(await _with_payouts(select((await _lobby())["gpps"], entries, fees, exclude)))
    return {
        "entry_groups": [{"id": gid, "label": label, "min": lo, "max": hi} for gid, label, lo, hi in ENTRY_GROUPS],
        "fee_groups": [{"id": gid, "label": label} for gid, label, _, _ in FEE_GROUPS],
        "kinds": CONTEST_KINDS,
        "default_weights": WEIGHTS,
        "max_weight": MAX_WEIGHT,
        "weights": normalize_weights(weights),
        "selected": {"entries": sorted(entries), "fees": sorted(fees), "excluded": sorted(exclude)},
        "matching": len(rows),
        "contests": score_contests(rows, weights)[:TOP_N],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
