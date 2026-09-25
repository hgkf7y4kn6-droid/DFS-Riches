"""Builds the Bayesian ownership report for a Classic slate (sections A-M).

compute()  posterior for every player and contest type (+ Showdown FLEX/CPT
           for players whose game has a Showdown slate), Monte Carlo for the
           selected contest, and a projection-history snapshot when anything
           changed before lock. Called before lineups are built, so the DFS
           strategy uses the posterior as ownership.
report()   everything else, once lineups exist: leverage vs your exposure,
           duplication, concentration, movement, crowd, disagreement...

Labels on every number: ACTUAL, PROJECTED (a source), CROWDSOURCED,
BAYESIAN POSTERIOR, SIMULATED.
"""
from __future__ import annotations

import statistics
from datetime import datetime

import numpy as np

from app import ownership_field as of
from app import ownership_model as om
from app import ownership_store as store

DEFAULT_CONTEST_SIZE = {"gpp": 20000, "se": 200, "3max": 5000, "20max": 20000, "150max": 100000, "cash": 100}
SALARY_BINS = [(0, 3999, "Under $4K"), (4000, 5999, "$4K-5.9K"), (6000, 7999, "$6K-7.9K"), (8000, 99999, "$8K+")]
CHALK_BUCKETS = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 25), (25, 30), (30, 101)]
SNAPSHOT_MOVE = 0.005


def classic_players(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if r["position"] not in om.CLASSIC_POS or r["salary"] <= 0:
            continue
        out.append({"key": store.player_key(r["name"], r["team"], r["position"]), "id": r["id"], "name": r["name"],
                    "team": r["team"], "opponent": r["opponent"], "position": r["position"], "salary": r["salary"],
                    "final": r.get("final") or 0.0, "value": r.get("value") or 0.0, "ceiling": r.get("ceiling") or 0.0,
                    "implied": r.get("implied"), "injury": r["injury"], "game": r.get("game"), "roster_slot": ""})
    return out


def showdown_players(sp_players: list, team_implied: dict) -> list[dict]:
    out = []
    for p in sp_players:
        if p.salary <= 0:
            continue
        base = store.player_key(p.name, p.team, p.position)
        out.append({"key": base + ("|CPT" if p.roster_slot == "CPT" else "|FLEX"), "base_key": base, "id": p.dk_draftable_id,
                    "name": p.name, "team": p.team, "opponent": p.opponent, "position": p.position, "salary": p.salary,
                    "final": p.proj_points or 0.0, "value": p.value_per_1k or 0.0, "ceiling": p.ceiling or 0.0,
                    "implied": team_implied.get(p.team), "injury": p.injury or "Healthy", "roster_slot": p.roster_slot})
    return out


def _mean(det: dict) -> float:
    return det["alpha"] / (det["alpha"] + det["beta"])


def compute(season: int, week: int, slate, rows: list[dict], *, contest: str = "gpp", now: datetime | None = None,
            showdowns: list[tuple] = (), write_history: bool = True) -> dict:
    now = now or om.now_utc()
    learning = store.load_learning()
    data = store.load(season, week, slate.slate_id)
    lock = min((g.kickoff_utc for g in slate.games), default=None)
    players = classic_players(rows)
    slots = om.classic_slots(learning)
    post = om.posterior(players, data["observations"], learning, now=now, lock=lock,
                        contests=store.CLASSIC_CONTESTS, group_of=lambda p: p["position"], slots=slots)
    by_c = post["by_contest"]
    keys = [p["key"] for p in players]
    det = by_c[contest]
    sim_keys = [k for k in keys if _mean(det[k]) >= om.SIM_MIN_MEAN]
    sim = om.simulate(det, sim_keys)
    sim["stats"].update(om.analytic_stats(det, [k for k in keys if k not in sim["stats"]]))

    # --- projection history (append-only, pre-lock only)
    history = data.get("history") or []
    statuses = {p["key"]: p["injury"] for p in players}
    n_obs = len(data["observations"])
    wrote = None
    if write_history and (lock is None or now < lock):
        last = history[-1] if history else None
        trigger = None
        if last is None:
            trigger = "Opening projection"
        elif last.get("n_obs") != n_obs:
            trigger = "New ownership information"
        elif last.get("statuses") != statuses:
            changed = [k for k in statuses if (last.get("statuses") or {}).get(k) != statuses[k]]
            trigger = "Injury status change: " + ", ".join(changed[:5])
        else:
            prev = (last.get("contests") or {}).get("gpp") or {}
            moved = [k for k in keys if k in prev and abs(_mean(by_c["gpp"][k]) - prev[k][0] / sum(prev[k])) >= SNAPSHOT_MOVE]
            if moved:
                trigger = f"Projection / salary / news refresh ({len(moved)} players moved 0.5+ pts)"
        if trigger:
            keep = [k for k in keys if _mean(by_c["gpp"][k]) >= 0.005 or (last and k in ((last.get("contests") or {}).get("gpp") or {}))]
            snap = {"timestamp": store.now_iso(), "trigger": trigger, "n_obs": n_obs, "statuses": statuses,
                    "contests": {c: {k: [round(by_c[c][k]["alpha"], 3), round(by_c[c][k]["beta"], 3)] for k in keep}
                                 for c in store.CLASSIC_CONTESTS}}
            features = {"z": post["features"], "slots": slots,
                        "roster": {p["key"]: [p["position"], p["team"], p["opponent"], p["salary"]] for p in players}}
            store.append_history(season, week, slate.slate_id, snap, features, lock.isoformat() if lock else None)
            history = history + [snap]
            wrote = trigger

    # --- showdown (players whose game has a Showdown slate)
    sd = {}
    for sd_slate, sd_players in showdowns:
        sd_data = store.load(season, week, sd_slate.slate_id)
        sd_lock = min((g.kickoff_utc for g in sd_slate.games), default=None)
        spost = om.posterior(sd_players, sd_data["observations"], learning, now=now, lock=sd_lock,
                             contests=("showdown_flex", "showdown_cpt"), group_of=lambda p: p["roster_slot"],
                             slots=om.SHOWDOWN_SLOTS,
                             contest_of_group=lambda p: "showdown_cpt" if p["roster_slot"] == "CPT" else "showdown_flex")
        for p in sd_players:
            c = "showdown_cpt" if p["roster_slot"] == "CPT" else "showdown_flex"
            det = spost["by_contest"][c].get(p["key"])
            if det:
                s = om.beta_summary(det["alpha"], det["beta"])
                sd.setdefault(p["base_key"], {"slate": sd_slate.label})[p["roster_slot"].lower()] = {
                    "mean": s["mean"], "ci80": s["ci80"], "actual": det.get("actual")}

    return {"players": players, "post": post, "sim": sim, "contest": contest, "history": history, "lock": lock,
            "now": now, "data": data, "learning": learning, "showdown": sd, "history_written": wrote, "slots": slots}


def own_pct_by_id(state: dict, contest: str = "gpp") -> dict[int, float]:
    det = state["post"]["by_contest"][contest]
    return {p["id"]: round(_mean(det[p["key"]]) * 100, 2) for p in state["players"]}


def _pct(x):
    return None if x is None else round(x * 100, 2)


def _movement(state: dict, contest: str) -> dict[str, dict]:
    hist = state["history"]
    if not hist:
        return {}
    first = hist[0]
    t0 = store.parse_iso(first["timestamp"])
    hours = max(0.0, (state["now"] - t0).total_seconds() / 3600)
    htl = state["post"]["hours_to_lock"]
    sim = state["sim"]
    out = {}
    open_c = (first.get("contests") or {}).get(contest) or {}
    for j, k in enumerate(sim["keys"]):
        if k not in open_c:
            continue
        a, b = open_c[k]
        opening = a / (a + b)
        cur = sim["stats"][k]["mean"]
        vel = (cur - opening) / hours if hours >= 0.25 else 0.0
        target = cur + max(0.01, vel * max(0.0, htl)) if vel > 0 else cur + 0.01
        p_inc = float((sim["draws"][:, j] > target).mean())
        out[k] = {"opening": _pct(opening), "current": _pct(cur), "change": _pct(cur - opening),
                  "change_pct": round((cur - opening) / opening * 100, 1) if opening > 0.001 else None,
                  "velocity_per_hour": _pct(vel), "p_further_increase": p_inc, "target": _pct(target),
                  "opened_at": first["timestamp"]}
    return out


def report(state: dict, *, contest: str, contest_size: int | None, model_lineups: dict[str, list[int]],
           exposure_lineups: list[list[int]]) -> dict:
    players = state["players"]
    by_c = state["post"]["by_contest"]
    sim = state["sim"]
    stats_ = sim["stats"]
    learning = state["learning"]
    det_c = by_c[contest]
    key_of_id = {p["id"]: p["key"] for p in players}
    contest_size = contest_size or DEFAULT_CONTEST_SIZE.get(contest, 20000)
    prev_snap = state["history"][-2] if len(state["history"]) >= 2 else None
    prev = ((prev_snap or {}).get("contests") or {}).get(contest)
    spikes = om.spikes(sim, prev)
    movement = _movement(state, contest)

    # --- A/B/I/K/L table
    table = []
    for p in players:
        k = p["key"]
        d = det_c[k]
        s = stats_[k]
        quality, qwhy = om.info_quality(d)
        m = d.get("models") or {}
        a_m, b_m, c_m = m.get("A"), m.get("B"), m.get("C")
        contest_cols = {c: _pct(_mean(by_c[c][k])) for c in store.CLASSIC_CONTESTS}
        sd = state["showdown"].get(k)
        mv = movement.get(k, {})
        table.append({
            "key": k, "id": p["id"], "name": p["name"], "position": p["position"], "team": p["team"], "opponent": p["opponent"],
            "salary": p["salary"], "injury": p["injury"], "game": p.get("game"),
            "mean": _pct(s["mean"]), "median": _pct(s["median"]), "mode": _pct(s["mode"]), "sd": _pct(s["sd"]),
            "ci50": [_pct(x) for x in s["ci50"]], "ci80": [_pct(x) for x in s["ci80"]], "ci95": [_pct(x) for x in s["ci95"]],
            "p_over": {t: round(v, 3) for t, v in s["p_over"].items()}, "rank_mean": round(s["rank_mean"], 1) if s["rank_mean"] is not None else None, "rank_probs": {t: round(v, 3) for t, v in s["rank_probs"].items()},
            "p_top5": round(s["p_top5"], 3), "p_top10": round(s["p_top10"], 3),
            "contests": contest_cols,
            "showdown": sd and {"slate": sd["slate"], "flex": sd.get("flex") and _pct(sd["flex"]["mean"]),
                                "cpt": sd.get("cpt") and _pct(sd["cpt"]["mean"])},
            "crowd": _pct(b_m["mu"]) if b_m else None, "crowd_users": b_m["users"] if b_m else 0,
            "sources_mean": _pct(a_m["mu"]) if a_m and a_m["mu"] is not None else None, "n_sources": a_m["k"] if a_m else 0,
            "dispersion": _pct(a_m["dispersion"]) if a_m else None,
            "source_parts": a_m["parts"] if a_m else [],
            "model_c": _pct(c_m["mu"]) if c_m else None, "n_c": round(c_m["n"], 1) if c_m else None,
            "n_a": round(a_m["n"], 1) if a_m else 0, "n_b": round(b_m["n"], 1) if b_m else 0,
            "n_total": round(d["alpha"] + d["beta"], 1),
            "trend": mv.get("change"), "movement": mv or None, "spike": spikes.get(k),
            "confidence": quality, "confidence_why": qwhy, "news": d.get("news"), "calibrated": d.get("calibrated", False),
            "actual": d.get("actual"),
        })
    table.sort(key=lambda r: -(r["mean"] or 0))
    for i, r in enumerate(table):
        r["rank"] = i + 1

    means = {r["key"]: r["mean"] or 0 for r in table}
    total_mass = sum(means.values()) or 1

    def conc(group_of):
        agg: dict[str, float] = {}
        for r in table:
            agg[group_of(r)] = agg.get(group_of(r), 0.0) + (r["mean"] or 0)
        return [{"group": g, "ownership": round(v, 1), "share": round(v / total_mass, 3)}
                for g, v in sorted(agg.items(), key=lambda kv: -kv[1])]

    top = [r["mean"] or 0 for r in table]
    concentration = {
        "total_roster_pct": round(total_mass, 1),
        "top": {str(n): {"ownership": round(sum(top[:n]), 1), "share": round(sum(top[:n]) / total_mass, 3)} for n in (5, 10, 20)},
        "position": conc(lambda r: r["position"]), "team": conc(lambda r: r["team"]), "game": conc(lambda r: r["game"] or "-"),
        "salary": conc(lambda r: next(label for lo, hi, label in SALARY_BINS if lo <= r["salary"] <= hi)),
    }
    chalk_dist = [{"range": f"{lo}-{hi}%" if hi <= 100 else f"{lo}%+", "count": sum(1 for r in table if lo <= (r["mean"] or 0) < hi)}
                  for lo, hi in CHALK_BUCKETS]
    chalk_dist[-1]["range"] = "30%+"

    # --- D: sources
    src_rows: dict[str, dict] = {}
    for r in table:
        for part in r["source_parts"]:
            s = src_rows.setdefault(part["source"], {"source": part["source"], "players": 0, "weights": [], "n": [],
                                                      "ages": [], "scored": part["scored"]})
            s["players"] += 1
            s["weights"].append(part["weight"])
            s["n"].append(part["n"])
            s["ages"].append(part["age_h"])
    lsrc = learning.get("sources") or {}
    sources = []
    for name, s in src_rows.items():
        st = lsrc.get(name) or {}
        sources.append({"source": name, "players": s["players"], "scored": s["scored"],
                        "mae": _pct(st.get("mae")), "bias": _pct(st.get("bias")), "rmse": _pct(st.get("rmse")),
                        "graded_n": st.get("n", 0), "reliability": round(1 / ((st.get("mae") or om.SOURCE_SIGMA_DEFAULT * 0.8) + om.EPS), 1),
                        "avg_effective_n": round(statistics.fmean(s["n"]), 1), "avg_age_h": round(statistics.fmean(s["ages"]), 1)})
    corr = [{"pair": k, **v} for k, v in (learning.get("source_corr") or {}).items()]

    # --- E: crowd dashboard
    crowd_obs = [o for o in state["data"]["observations"] if o["kind"] == "crowd"]
    users = {o.get("user_id") for o in crowd_obs}
    luser = learning.get("users") or {}
    crowd_players = [r for r in table if r["crowd"] is not None]
    crowd_vals = [r["crowd"] for r in crowd_players]
    crowd = {
        "contributors": len(users), "submissions": len(crowd_obs),
        "players_covered": len(crowd_players),
        "average": round(statistics.fmean(crowd_vals), 2) if crowd_vals else None,
        "median": round(statistics.median(crowd_vals), 2) if crowd_vals else None,
        "sd": round(statistics.pstdev(crowd_vals), 2) if len(crowd_vals) > 1 else None,
        "historical_mae": _pct((learning.get("crowd") or {}).get("mae")),
        "high_reliability": sum(1 for u in users if (luser.get(u) or {}).get("n", 0) >= 20 and (luser.get(u) or {}).get("mae", 1) <= 0.03),
        "players": [{"name": r["name"], "position": r["position"], "crowd": r["crowd"], "bayesian": r["mean"],
                     "difference": round(r["crowd"] - r["mean"], 2), "users": r["crowd_users"]}
                    for r in sorted(crowd_players, key=lambda r: -abs(r["crowd"] - r["mean"]))[:40]],
    }

    # --- F: disagreement
    disagreement = [{"name": r["name"], "position": r["position"], "dispersion": r["dispersion"], "n_sources": r["n_sources"],
                     "ci80_width": round(r["ci80"][1] - r["ci80"][0], 1), "mean": r["mean"],
                     "crowd_gap": round(r["crowd"] - r["mean"], 1) if r["crowd"] is not None else None}
                    for r in table if (r["dispersion"] or 0) > om.DISPERSION_FLAG * 100
                    or (r["crowd"] is not None and abs(r["crowd"] - r["mean"]) >= 3)]

    # --- J: late news
    first = state["history"][0] if state["history"] else None
    news = []
    for r in table:
        if r["news"] and r["news"].startswith("Confirmed"):
            news.append({"name": r["name"], "team": r["team"], "position": r["position"], "text": r["news"], "kind": "ACTUAL news"})
    if first:
        open_status = first.get("statuses") or {}
        cur_status = {r["key"]: r["injury"] for r in table}
        changed_teams = {r["team"] for r in table if open_status.get(r["key"], r["injury"]) != r["injury"]}
        for r in table:
            if open_status.get(r["key"], r["injury"]) != r["injury"]:
                news.append({"name": r["name"], "team": r["team"], "position": r["position"], "kind": "Status change",
                             "text": f"{open_status.get(r['key'])} -> {cur_status[r['key']]} since the opening projection"})
        for r in table:
            mv = r["movement"] or {}
            if r["team"] in changed_teams and mv.get("change") is not None and abs(mv["change"]) >= 2:
                news.append({"name": r["name"], "team": r["team"], "position": r["position"], "kind": "Teammate reaction",
                             "text": f"Posterior {mv['change']:+.1f} pts since opening after a {r['team']} status change"})

    # --- 14: leverage vs exposure
    def exposure(lineups):
        if not lineups:
            return {}
        cnt: dict[str, int] = {}
        for lu in lineups:
            for pid in lu:
                k = key_of_id.get(pid)
                if k:
                    cnt[k] = cnt.get(k, 0) + 1
        return {k: v / len(lineups) for k, v in cnt.items()}

    model_exp = exposure(exposure_lineups)
    lev_rows = []
    for r in table:
        e = model_exp.get(r["key"], 0.0) * 100
        if e > 0 or (r["mean"] or 0) >= 10:
            lev_rows.append({"name": r["name"], "position": r["position"], "field": r["mean"], "exposure": round(e, 1),
                             "leverage": round((r["mean"] or 0) - e, 1),
                             "relative": round(e / r["mean"], 2) if r["mean"] else None})
    lev_rows.sort(key=lambda x: -abs(x["leverage"]))

    # --- H: duplication (SIMULATED)
    ab = np.array([[det_c[p["key"]]["alpha"], det_c[p["key"]]["beta"]] for p in players])
    field_players = [p for p in players]
    fm = of.FieldModel(field_players, ab[:, 0], ab[:, 1], om.flex_shares(learning),
                       learning.get("field"))
    lu_keys = {label: [key_of_id.get(pid) for pid in ids] for label, ids in model_lineups.items()}
    lu_keys = {k: v for k, v in lu_keys.items() if all(v)}
    dup = of.duplication(fm, lu_keys, contest_size)
    sim_own = dup.pop("sim_own", None)
    if sim_own is not None:
        diffs = [abs(sim_own[i] * 100 - (means.get(p["key"]) or 0)) for i, p in enumerate(field_players)]
        dup["simulated_vs_posterior_mae"] = round(statistics.fmean(diffs), 2)

    lm = learning.get("model") or {}
    info_counts: dict[str, int] = {}
    for r in table:
        info_counts[r["confidence"]] = info_counts.get(r["confidence"], 0) + 1

    return {
        "contest": contest, "contest_label": store.CONTESTS[contest], "contest_size": contest_size,
        "contest_sizes": DEFAULT_CONTEST_SIZE, "contests": store.CONTESTS,
        "generated_at": store.now_iso(), "lock": state["lock"].isoformat() if state["lock"] else None,
        "hours_to_lock": round(state["post"]["hours_to_lock"], 2), "history_written": state["history_written"],
        "table": [{k: v for k, v in r.items() if k != "movement"} for r in table
                  if (r["mean"] or 0) >= 0.3 or r["actual"] is not None or r["news"]],
        "table_omitted": sum(1 for r in table if not ((r["mean"] or 0) >= 0.3 or r["actual"] is not None or r["news"])),
        "concentration": concentration, "chalk_distribution": chalk_dist,
        "sources": sources, "source_corr": corr, "crowd": crowd, "disagreement": disagreement[:40],
        "late_news": news[:40], "leverage": lev_rows[:60], "duplication": dup,
        "spikes": [{"name": r["name"], **r["spike"]} for r in table if r.get("spike") and r["spike"]["flag"]],
        "movement": [{"name": r["name"], "position": r["position"], **r["movement"]} for r in table
                     if r["movement"] and (r["mean"] or 0) >= 3][:40],
        "history": [{"timestamp": h["timestamp"], "trigger": h["trigger"], "n_obs": h.get("n_obs")} for h in state["history"]],
        "history_series": _history_series(state, contest, [r["key"] for r in table[:12]]),
        "model_state": {
            "behavioral_trained": state["post"]["trained"], "behavioral_n": state["post"]["n_behavioral"],
            "behavioral_coef": state["post"]["coef"], "slots": state["slots"],
            "calibrated": (learning.get("calibration") or {}).get("n", 0) >= 100,
            "calibration_n": (learning.get("calibration") or {}).get("n", 0),
            "slates_with_actuals": learning.get("slates_with_actuals", 0),
            "accuracy": lm, "contest_adjust": learning.get("contest_adjust") or {},
            "field_params": dup.get("params"), "field_learned": bool(learning.get("field")),
            "confidence_counts": info_counts, "learned_at": learning.get("generated_at"),
        },
        "defaults": {"behavioral_n": om.N_BEHAVIORAL_UNTRAINED, "source_sigma": om.SOURCE_SIGMA_DEFAULT * 100,
                     "source_rho": om.SOURCE_RHO_DEFAULT, "crowd_mae": om.CROWD_MAE_DEFAULT * 100,
                     "crowd_rho": om.CROWD_RHO_DEFAULT, "transfer": om.TRANSFER, "flex": om.DEFAULT_FLEX,
                     "field": of.FIELD_DEFAULTS},
    }


def _history_series(state: dict, contest: str, keys: list[str]) -> list[dict]:
    out = []
    names = {p["key"]: p["name"] for p in state["players"]}
    for k in keys:
        pts = []
        for h in state["history"]:
            ab = ((h.get("contests") or {}).get(contest) or {}).get(k)
            if ab:
                pts.append({"t": h["timestamp"], "mean": round(ab[0] / (ab[0] + ab[1]) * 100, 2)})
        if pts:
            out.append({"key": k, "name": names.get(k, k), "points": pts})
    return out
