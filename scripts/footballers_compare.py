"""Compare an outside source's DFS notes (here The Fantasy Footballers' Week 9 DraftKings ownership notes, transcribed
from screenshots into data/footballers/w9_source.json) against the model, build GPP lineups from both, and grade them
once the slate is final.

    python -m scripts.footballers_compare compare      # source vs model snapshot: projection, ownership, salary gaps
    python -m scripts.footballers_compare lineups      # 5 GPP lineups from the blended projections + ownership leverage
    python -m scripts.footballers_compare grade        # after the slate: projection MAE, claims, pivots, lineup scores

`data/footballers/w9_model_snapshot.json` is the model's pre-lock projections and ownership posterior, so the grade
compares what each side said *before* kickoff. Actual ownership isn't in any box score: grade only scores ownership
if actuals were uploaded (data/ownership/*), otherwise it reports the source-vs-model gap only.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
from pathlib import Path

from app.config import DATA_DIR

D = DATA_DIR / "footballers"
SOURCE, SNAP = D / "w9_source.json", D / "w9_model_snapshot.json"
SOURCE2, LINEUPS1 = D / "w9_source2.json", D / "w9_lineups_v1.json"
LINEUPS, GRADE = D / "w9_lineups.json", D / "w9_grade.json"
CASH_SRC, CASH = D / "w9_source_cash.json", D / "w9_cash_lineups.json"
SLATE = ("classic_sunday", 2026, 9)
BAD_PROJ: set = set()      # (name, pos) pairs whose source projection is a known typo and should be ignored


def _norm(n: str) -> str:
    n = re.sub(r"[.']", "", n.lower())
    n = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()


def load() -> tuple[list[dict], list[dict], dict]:
    src, snap = json.loads(SOURCE.read_text()), json.loads(SNAP.read_text())
    model = snap["players"]
    idx: dict = {}
    for p in model:
        idx.setdefault((_norm(p["name"]), p["pos"]), []).append(p)
    rows = []
    for s in src["players"]:
        if s["pos"] == "DST":
            c = [m for m in model if m["pos"] == "DST" and m["team"] == s["name"]]
        else:
            c = idx.get((_norm(s["name"]), s["pos"]), [])
        if len(c) == 1:
            rows.append({**s, "m": c[0]})
    return rows, model, src


def load2(model: list[dict]) -> dict[int, dict]:
    """The large-field GPP article (data/footballers/w9_source2.json) by model player id."""
    out = {}
    for s in json.loads(SOURCE2.read_text())["players"]:
        m = find(model, s["name"], s["pos"])
        if m:
            out[m["id"]] = s
    return out


def find(model: list[dict], name: str, pos: str) -> dict | None:
    if pos == "DST":
        return next((m for m in model if m["pos"] == "DST" and m["team"] == name), None)
    return next((m for m in model if m["pos"] == pos and _norm(m["name"]) == _norm(name)), None)


def cmd_compare() -> None:
    rows, _model, _src = load()
    both = [r for r in rows if r["proj"] is not None and r["m"]["proj"]]
    print(f"{len(rows)} source players matched to the model; {len(both)} with a source projection")
    for pos in ("QB", "RB", "WR", "TE", "DST"):
        g = [r for r in both if r["pos"] == pos and (r["name"], pos) not in BAD_PROJ]
        if not g:
            continue
        dp = [r["proj"] - r["m"]["proj"] for r in g]
        do = [r["own"] - (r["m"]["own"] or 0) for r in rows if r["pos"] == pos]
        print(f"{pos}: proj source-model mean {statistics.mean(dp):+.2f} (abs {statistics.mean(abs(x) for x in dp):.2f}); "
              f"own source-model mean {statistics.mean(do):+.2f} (abs {statistics.mean(abs(x) for x in do):.2f}, n={len(do)})")
    print("\nBiggest ownership gaps (source - model, pct pts):")
    for r in sorted(rows, key=lambda r: -abs(r["own"] - (r["m"]["own"] or 0)))[:12]:
        print(f"  {r['name']:<22}{r['pos']:<4} ${r['m']['salary']:<6} source {r['own']:>5.1f}%  model {r['m']['own'] or 0:>5.1f}%")
    print("\nBiggest projection gaps (source - model):")
    for r in sorted([r for r in both if (r["name"], r["pos"]) not in BAD_PROJ], key=lambda r: -abs(r["proj"] - r["m"]["proj"]))[:12]:
        print(f"  {r['name']:<22}{r['pos']:<4} ${r['m']['salary']:<6} source {r['proj']:>5.1f}  model {r['m']['proj']:>5.1f}")


def _pool(model: list[dict], rows: list[dict]) -> tuple[list[dict], list[float]]:
    """Blend the model with both sources: equal-weight mean of whichever projections, ownerships and ceilings exist."""
    from app.optimizer import ELIGIBLE_STATUSES
    byid = {r["m"]["id"]: r for r in rows}
    two = load2(model)
    pool, vals = [], []
    for m in model:
        if not (m["salary"] > 0 and (m["proj"] or 0) > 0 and m["inj"] in ELIGIBLE_STATUSES):
            continue
        if m["pos"] != "DST" and m["proj"] < 6:
            continue
        s1, s2 = byid.get(m["id"]), two.get(m["id"])
        projs = [m["proj"]] + [x["proj"] for x in (s1, s2) if x and x.get("proj") is not None and (x["name"], x["pos"]) not in BAD_PROJ]
        proj = statistics.mean(projs)
        owns = [o for o in (m["own"], s1["own"] if s1 else None, s2["own"] if s2 else None) if o is not None]
        own = statistics.mean(owns) if owns else 5.0
        ceils = [c for c in (m["ceil"] or m["proj"], s2.get("ceil") if s2 else None) if c is not None]
        gap = max(statistics.mean(ceils) - proj, 0)
        # GPP value: blended projection, a ceiling bonus, and a leverage penalty on blended ownership
        v = proj + 0.12 * gap - 0.05 * own
        pool.append({"id": m["id"], "name": m["name"], "position": m["pos"], "team": m["team"], "opponent": m["opp"],
                     "salary": m["salary"], "game": m["game"], "proj": round(proj, 2), "own": round(own, 1), "inj": m["inj"]})
        vals.append(v)
    return pool, vals


QB_PLANS = [("Goff stack (St. Brown/Jameson, MIA return)", "Jared Goff"), ("Stafford stack (Puka, WAS return)", "Matthew Stafford"),
            ("Love stack (Watson/Kraft, NE return)", "Jordan Love"), ("Mahomes stack (Rice/Kelce)", "Patrick Mahomes"),
            ("Daniels stack (WAS, Puka/LAR return)", "Jayden Daniels")]


def cmd_cash() -> None:
    """Three cash lineups: highest blended projection from the cash article's pool plus the Core Plays tables,
    healthy players only, no leverage or ceiling adjustments (cash wants the floor)."""
    from app import lineup_builder
    rows, model, _src = load()
    src = json.loads(CASH_SRC.read_text())
    names = {(p["name"], p["pos"]) for p in src["article_cash_plays"]}
    names |= {(n, pos) for pos, ns in src["core_plays"].items() for n in ns}
    allowed = {m["id"] for n, pos in names if (m := find(model, n, pos))}
    byid = {r["m"]["id"]: r for r in rows}
    two = load2(model)
    pool, vals = [], []
    for m in model:
        if m["id"] not in allowed or m["inj"] != "Healthy" or not (m["salary"] > 0 and (m["proj"] or 0) > 0):
            continue
        s1, s2 = byid.get(m["id"]), two.get(m["id"])
        projs = [m["proj"]] + [x["proj"] for x in (s1, s2) if x and x.get("proj") is not None]
        proj = statistics.mean(projs)
        pool.append({"id": m["id"], "name": m["name"], "position": m["pos"], "team": m["team"], "opponent": m["opp"],
                     "salary": m["salary"], "game": m["game"], "proj": round(proj, 2), "own": m["own"] or 0.0, "inj": m["inj"]})
        vals.append(proj)
    out, prior = [], []
    for k in range(3):
        lu = lineup_builder.build(pool, vals, prior=prior, min_unique=5)
        if not lu:
            print(f"cash #{k + 1}: no feasible lineup")
            break
        prior.append({p["id"] for p in lu})
        out.append({"label": f"Cash #{k + 1}", "players": [{x: p[x] for x in ("id", "name", "position", "team", "opponent", "salary", "proj", "own", "inj")} for p in lu],
                    "salary": sum(p["salary"] for p in lu), "proj": round(sum(p["proj"] for p in lu), 2)})
    CASH.write_text(json.dumps({"saved": "pre-lock", "lineups": out}, indent=1))
    print(f"cash pool: {len(pool)} healthy players")
    for i, lu in enumerate(out, 1):
        print(f"\nCash #{i}  ${lu['salary']}  blended proj {lu['proj']}")
        for p in lu["players"]:
            print(f"   {p['position']:<4}{p['name']:<24}{p['team']:<4}${p['salary']:<6}{p['proj']:>5.1f}")


def cmd_lineups() -> None:
    from app import lineup_builder
    from app import dfs_strategy
    rows, model, _src = load()
    pool, vals = _pool(model, rows)
    out, prior = [], []
    used: dict[int, int] = {}
    base = list(vals)
    for label, qb in QB_PLANS:
        # exposure control: each earlier use of a player costs him 1.2 value points, so the five lineups differ
        vals = [v - 1.2 * used.get(p["id"], 0) for v, p in zip(base, pool)]
        if qb:
            ids = {p["id"] for p in pool if p["position"] == "QB" and _norm(p["name"]) == _norm(qb)}
        else:
            ids = {p["id"] for p in pool if p["position"] == "QB" and p["name"] in ("Drake Maye", "Jordan Love", "Tyler Shough")}
        lu = None
        for kw in (dict(stack=(2, 1), bring_back_pos=("WR", "TE")), dict(stack=(2, 1)), dict(stack=(1, 1))):
            lu = lineup_builder.build(pool, vals, prior=prior, min_unique=4, qb_ids=ids, min_salary=dfs_strategy.GPP_MIN_SALARY,
                                      one_rb_per_team=True, **kw)
            if lu:
                break
        if not lu:
            print(f"{label}: no feasible lineup")
            continue
        prior.append({p["id"] for p in lu})
        for p in lu:
            used[p["id"]] = used.get(p["id"], 0) + 1
        out.append({"label": label, "players": [{k: p[k] for k in ("id", "name", "position", "team", "opponent", "salary", "proj", "own", "inj")} for p in lu],
                    "salary": sum(p["salary"] for p in lu), "proj": round(sum(p["proj"] for p in lu), 2),
                    "own_sum": round(sum(p["own"] for p in lu), 1)})
    LINEUPS.write_text(json.dumps({"saved": "pre-lock", "lineups": out}, indent=1))
    for i, lu in enumerate(out, 1):
        print(f"\n#{i} {lu['label']}  ${lu['salary']}  blended proj {lu['proj']}  summed own {lu['own_sum']}%")
        for p in lu["players"]:
            print(f"   {p['position']:<4}{p['name']:<24}{p['team']:<4}${p['salary']:<6}{p['proj']:>5.1f}  {p['own']:>5.1f}%" + ("" if p["inj"] == "Healthy" else f"  [{p['inj']}]"))


async def cmd_grade(force: bool = False) -> None:
    from app import nflverse_client as nc
    rows, model, src = load()
    from app import optimal, slates
    actuals = await nc.get_week_actuals(2026, 9)
    _sched, slate_list = await slates.list_slates(2026, 9)
    slate = next(s for s in slate_list if s.slate_id == SLATE[0])
    if not optimal.slate_complete(slate, actuals) and not force:
        done = sum(1 for g in slate.games if g.context is not None and g.context.is_final)
        print(f"Not graded: {done} of {len(slate.games)} games on the {SLATE[0]} slate are final (use --force to grade anyway).")
        return

    def act(m):
        return nc.actual_points(actuals, name=m["name"], position=m["pos"], team=m["team"])

    rep: dict = {"projection": {}, "claims": [], "pivots": [], "lineups": []}
    graded = [(r, act(r["m"])) for r in rows if r["proj"] is not None and r["m"]["proj"] >= 3 and (r["name"], r["pos"]) not in BAD_PROJ]
    for pos in ("QB", "RB", "WR", "TE", "DST", "ALL"):
        g = [(r, a) for r, a in graded if pos in ("ALL", r["pos"])]
        if g:
            rep["projection"][pos] = {"n": len(g), "source_mae": round(statistics.mean(abs(r["proj"] - a) for r, a in g), 2),
                                      "model_mae": round(statistics.mean(abs(r["m"]["proj"] - a) for r, a in g), 2),
                                      "source_bias": round(statistics.mean(r["proj"] - a for r, a in g), 2),
                                      "model_bias": round(statistics.mean(r["m"]["proj"] - a for r, a in g), 2)}
    two = load2(model)
    g2 = [(x, next(m for m in model if m["id"] == i), ) for i, x in two.items() if x.get("proj") is not None]
    g2 = [(x, m, act(m)) for x, m in g2 if m["proj"] >= 3]
    if g2:
        rep["projection_source2"] = {"n": len(g2), "source2_mae": round(statistics.mean(abs(x["proj"] - a) for x, m, a in g2), 2),
                                     "model_mae": round(statistics.mean(abs(m["proj"] - a) for x, m, a in g2), 2),
                                     "source1_mae_same_players": None,
                                     "source2_bias": round(statistics.mean(x["proj"] - a for x, m, a in g2), 2),
                                     "model_bias": round(statistics.mean(m["proj"] - a for x, m, a in g2), 2)}
        s1 = {r["m"]["id"]: r for r in rows if r["proj"] is not None}
        both = [(s1[m["id"]]["proj"], a) for x, m, a in g2 if m["id"] in s1]
        if both:
            rep["projection_source2"]["source1_mae_same_players"] = round(statistics.mean(abs(p_ - a) for p_, a in both), 2)
    def pts(name, pos):
        m = find(model, name, pos)
        return act(m) if m else None
    for c in src["claims"]:
        if "player" in c:
            a = pts(c["player"], c["pos"]); ok = None if a is None else a < c["under"]
            rep["claims"].append({"id": c["id"], "text": c["text"], "actual": a, "correct": ok})
        elif "top" in c:
            tes = [(r["m"], act(r["m"])) for r in rows if r["pos"] == c["pos"] and r["proj"] is not None]
            best = max(tes, key=lambda x: x[1])
            rep["claims"].append({"id": c["id"], "text": c["text"], "actual": f"top actual TE: {best[0]['name']} {best[1]}",
                                  "correct": best[0]["name"] == c["top"]})
        else:
            def side(x):
                if isinstance(x, list):
                    return sum(pts(n, "RB") or 0 for n in x)
                return pts(x, c["pos"])
            a, b = side(c["a"]), side(c["b"])
            rep["claims"].append({"id": c["id"], "text": c["text"], "a": a, "b": b, "correct": None if None in (a, b) else a > b})
    for pos, pop, low, agg in src["pivots"]:
        ap, al, ag = pts(pop, pos), pts(low, pos), pts(agg, pos)
        rep["pivots"].append({"pos": pos, "popular": [pop, ap], "pivot": [low, al], "aggressive": [agg, ag],
                              "pivot_beat_popular": None if None in (ap, al) else al > ap,
                              "aggressive_beat_popular": None if None in (ap, ag) else ag > ap})
    for tag, path in (("v2", LINEUPS), ("v1", LINEUPS1)):
        if path.exists():
            for lu in json.loads(path.read_text())["lineups"]:
                tot = 0.0
                for p in lu["players"]:
                    m = next((x for x in model if x["id"] == p["id"]), None)
                    tot += act(m) if m else 0
                rep["lineups"].append({"version": tag, "label": lu["label"], "proj": lu["proj"], "actual": round(tot, 2)})
    if CASH.exists():
        for lu in json.loads(CASH.read_text())["lineups"]:
            tot = sum(act(next(x for x in model if x["id"] == p["id"])) for p in lu["players"])
            rep["cash_lineups"] = rep.get("cash_lineups", []) + [{"label": lu["label"], "proj": lu["proj"], "actual": round(tot, 2)}]
        saved = optimal.load_saved(2026, 9, SLATE[0]) or {}
        rep["app_safe_lineup"] = [{"label": x.get("label"), "proj": x.get("proj_points"), "actual": x.get("actual")}
                                  for x in saved.get("lineups", []) if x.get("metric") in ("floor", "safe", "proj")]
        rep["note_cash"] = "Cash line (50/50, double-up) is not in any box score: compare 'actual' with the contest's cashing score once it is known."
    GRADE.write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["compare", "lineups", "cash", "grade"])
    ap.add_argument("--force", action="store_true", help="grade even if games are not final")
    args = ap.parse_args()
    cmd = args.cmd
    if cmd == "grade":
        asyncio.run(cmd_grade(args.force))
    else:
        {"compare": cmd_compare, "lineups": cmd_lineups, "cash": cmd_cash}[cmd]()


if __name__ == "__main__":
    main()
