"""Roster-move adjustments for the coming week, per team -> data/roster_adjust.json (read by app.roster_adjust).

    python -m scripts.update_roster_adjust [--season 2026] [--week N]

For every team it compares the lineup expected this week with the one its recent games came from, and applies only the
coefficients that held up out of sample (data/roster_adjust_model.json, fit by scripts.backtest_roster_moves):

  quarterback   expected starter's career dropback EPA (shrunk, 150 dropbacks) against the last starter's; a starter with
                under 300 career dropbacks also costs EPA, interceptions, sacks and red-zone TDs (vs the team's own baseline)
  receivers     WR/TE who had 8%+ of the team's last 4 games' targets and are out (DraftKings Out/IR) or traded away
  pass rush     each defender's own sacks+hits per snap (last 16 games, shrunk) carried to the team he is on now, against the
                players behind the team's last 4 games; converted to dropback EPA allowed

Expected starters default to the last game's starter; data/roster_adjust_inputs.json overrides them
({"expected_starters": {"MIN": "Kirk Cousins"}}, with a note that says who supplied it and whether it is confirmed).
Needs pandas and data/cache/train (play_by_play_YYYY.csv.gz, snap_counts_YYYY.csv, players.csv; see backtest_roster_moves).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app import nflverse_client as nc
from app import slates
from app.matching import normalize_name
from scripts import backtest_roster_moves as b

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "roster_adjust.json"
INPUTS = ROOT / "data" / "roster_adjust_inputs.json"
CONTEXT = ROOT / "data" / "context_changes.json"
MODEL = ROOT / "data" / "roster_adjust_model.json"
NOT_PLAYING = ("Out", "IR")
MOVE = re.compile(r"^(?P<name>.+?) \((?P<pos>[A-Z]+)\) (?P<old>[A-Z]+) -> (?P<new>[A-Z]+)")


def injured(season: int, week: int) -> dict[str, set[str]]:
    """{app team: normalized names} of players DraftKings lists Out/IR on the full-week slate."""
    sp = asyncio.run(slates.get_slate_players(season, week, "classic"))
    out: dict[str, set[str]] = {}
    for p in sp.players:
        if p.roster_slot in (None, "FLEX", "CPT") and (p.injury or "") in NOT_PLAYING:
            out.setdefault(p.team, set()).add(normalize_name(p.name))
    return out


def moves(week: int) -> tuple[dict, dict]:
    """({team: [(name, pos)] traded away}, {team: [(name, pos)] added}) effective by `week`."""
    gone, added = {}, {}
    for c in json.loads(CONTEXT.read_text())["changes"]:
        if int(c["season"]) != 2026 or c.get("effective_week") is None or int(c["effective_week"]) > week:
            continue
        m = MOVE.match(c.get("note", ""))
        if not m or c["type"] not in ("trade_in", "trade_out"):
            continue
        (added if c["type"] == "trade_in" else gone).setdefault(c["team"], []).append((m["name"], m["pos"]))
    return gone, added


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int, default=None)
    a = ap.parse_args()
    model = json.loads(MODEL.read_text())
    inputs = json.loads(INPUTS.read_text()) if INPUTS.exists() else {}
    seasons = list(range(2016, a.season + 1))

    p = b.load_pbp(seasons)
    g, pb, tg = b.team_games(p)
    week = a.week or int(g[g.season == a.season].week.max()) + 1
    pl = b.load_ids()
    full = pd.read_csv(b.TRAIN / "players.csv", usecols=["gsis_id", "display_name", "position", "last_season"], low_memory=False)
    full = full.dropna(subset=["gsis_id"])
    full["norm"] = full.display_name.map(normalize_name)
    names = full.drop_duplicates("gsis_id").set_index("gsis_id")

    mu = float(g.epa_db_s.sum() / g.db.sum())
    lg_pass = float(g.neutral_db.sum() / g.neutral_n.sum())
    # QB career as of now
    car = pb.groupby("passer_player_id").agg(n=("n", "sum"), s=("s", "sum"))
    car["rating"] = (car.s + b.K_QB * mu) / (car.n + b.K_QB)

    def qb_state(gsis: str | None):
        if gsis is None or gsis not in car.index:
            return mu - 0.12, 0.0
        return float(car.loc[gsis, "rating"]), float(car.loc[gsis, "n"])

    def find_qb(name: str) -> str | None:
        c = full[(full.norm == normalize_name(name)) & (full.position == "QB")].sort_values("last_season")
        return c.gsis_id.iloc[-1] if len(c) else None

    # ---- defenders: events and snaps over the last two seasons
    q = p[(p.qb_dropback == 1) & p.epa.notna()]
    ev = pd.concat([q[q[c].notna()][b.KEY + ["defteam", c]].rename(columns={c: "pid"}) for c in
                    ["sack_player_id", "half_sack_1_player_id", "half_sack_2_player_id", "qb_hit_1_player_id", "qb_hit_2_player_id"]])
    ev = ev.groupby(b.KEY + ["defteam", "pid"]).size().rename("ev").reset_index().rename(columns={"defteam": "team"})
    sn = b.load_snaps(pl, range(2025, a.season + 1))
    pg = sn[sn.defense_snaps > 0].merge(ev[["season", "week", "team", "pid", "ev"]], on=["season", "week", "team", "pid"], how="left").fillna({"ev": 0})
    pg = pg.sort_values(["pid", "season", "week"])
    lg_rate = pg.ev.sum() / pg.defense_snaps.sum()
    last16 = pg.groupby("pid").tail(16).groupby("pid").agg(e=("ev", "sum"), s=("defense_snaps", "sum"))
    last16["rate"] = (last16.e + b.K_SNAPS * lg_rate) / (last16.s + b.K_SNAPS)
    avg4 = pg.groupby("pid").tail(4).groupby("pid").defense_snaps.mean()
    db_mean = float(g.db.mean())

    inj = injured(a.season, week)
    games = asyncio.run(nc.get_games_raw(a.season))
    next_week = {}
    for r in games:
        if r.get("game_type") == "REG" and int(r["week"]) >= week:
            for tm in (r["home_team"], r["away_team"]):
                next_week[tm] = min(next_week.get(tm, 99), int(r["week"]))
    teams = sorted(set(g[g.season == a.season].posteam))
    res = {}
    for t in teams:
        app_t = nc.to_app_team(t)
        gone, added = moves(next_week.get(t, week))        # a team on its bye is read for the game after it
        tg_t = g[g.posteam == t].sort_values(["season", "week"])
        last = tg_t.iloc[-1]
        reasons, d_epa, d_pass, d_int, d_sack, d_rz = [], 0.0, 0.0, 0.0, 0.0, 0.0
        # ---- quarterback
        old_id = last.qb
        exp = (inputs.get("expected_starters") or {}).get(app_t)
        new_id = find_qb(exp["name"] if isinstance(exp, dict) else exp) if exp else old_id
        r_old, n_old = qb_state(old_id)
        r_new, n_new = qb_state(new_id)
        if new_id != old_id:
            nm_old = names.display_name.get(old_id, old_id)
            nm_new = names.display_name.get(new_id, exp if isinstance(exp, str) else (exp or {}).get("name"))
            gap = r_new - r_old
            d_epa += model["qb_gap_weight"]["epa_db"] * gap
            d_pass += model["qb_gap_weight"]["neutral_pass_rate"] * gap
            tag = "" if not isinstance(exp, dict) else f" ({exp.get('note')})"
            reasons.append(f"QB {nm_new}{tag} replaces {nm_old}: career EPA/dropback {r_new:+.2f} vs {r_old:+.2f} "
                           f"({int(n_new)} vs {int(n_old)} dropbacks)")
            inx_new, inx_old = n_new < model["inexperienced_below_career_dropbacks"], n_old < model["inexperienced_below_career_dropbacks"]
            if inx_new != inx_old:
                sgn = 1 if inx_new else -1
                ie = model["inexperienced_qb"]
                d_epa += sgn * ie["epa_db"]
                d_pass += sgn * ie["neutral_pass_rate"]
                d_int += sgn * ie["int_rate"]
                d_sack += sgn * ie["sack_rate"]
                d_rz += sgn * ie["rz_td_pct"]
                reasons.append(f"{nm_new} is inexperienced (<300 career dropbacks): more interceptions and sacks, fewer red-zone TDs"
                               if inx_new else f"Leaving {nm_old}'s inexperience behind (<300 career dropbacks): fewer interceptions and sacks, more red-zone TDs")
        # ---- receivers
        recent = tg_t[tg_t.season == a.season].tail(4)
        tt = tg[(tg.posteam == t) & tg.game_id.isin(recent.game_id)]
        tot = recent.tgt_n.sum()
        absent_norm = set(inj.get(app_t, set())) | {normalize_name(n) for n, pos in gone.get(app_t, [])}
        lost = 0.0
        lost_names = []
        if tot:
            for rid, v in (tt.groupby("receiver_player_id").tgt.sum() / tot).items():
                pos = names.position.get(rid)
                nm = names.display_name.get(rid)
                if pos in ("WR", "TE") and v >= model["lost_wr_te_target_share"]["min_share"] and nm and normalize_name(nm) in absent_norm:
                    lost += float(v)
                    lost_names.append(f"{nm} {v:.0%}")
        if lost:
            d_epa += model["lost_wr_te_target_share"]["epa_db"] * lost
            d_pass += model["lost_wr_te_target_share"]["neutral_pass_rate"] * lost
            reasons.append(f"WR/TE out or traded with {lost:.0%} of recent targets: " + ", ".join(lost_names))
        # ---- pass rush
        old_players = pg[(pg.team == t) & (pg.season == a.season)].merge(
            recent[["week"]], on="week").groupby("pid").defense_snaps.sum() / max(len(recent), 1)
        f_old = float(sum(last16.rate.get(pid, lg_rate) * s for pid, s in old_players.items()))
        keep = {pid: s for pid, s in old_players.items()          # who stays keeps the snaps he actually had
                if normalize_name(names.display_name.get(pid, "")) not in absent_norm}
        arrived = []
        for n, pos in added.get(app_t, []):
            c = full[(full.norm == normalize_name(n))].sort_values("last_season")
            if len(c) and pos in ("DT", "DL", "DE", "LB", "S", "CB", "OLB", "EDGE"):
                pid = c.gsis_id.iloc[-1]
                if pid in avg4.index:
                    keep[pid] = avg4[pid]
                    arrived.append((n, pos, float(last16.rate.get(pid, lg_rate))))
        f_new = float(sum(last16.rate.get(pid, lg_rate) * s for pid, s in keep.items()))
        d_events = model["pass_rush"]["forecast_weight"] * (f_new - f_old)      # sacks + QB hits per game
        d_def = model["pass_rush"]["epa_db_per_unit_pressure_rate"] * d_events / db_mean
        gone_def = [n for n, pos in gone.get(app_t, []) if pos in ("DT", "DL", "DE", "LB", "S", "CB")]
        out_def = [names.display_name.get(pid) for pid in old_players.index
                   if pid not in keep and names.position.get(pid) in ("DE", "DT", "NT", "DL", "LB", "OLB", "ILB")]
        if abs(d_events) >= 0.05:
            bits = []
            if arrived:
                bits.append("added " + ", ".join(f"{n} ({pos})" for n, pos, _ in arrived))
            if out_def or gone_def:
                bits.append("without " + ", ".join(sorted({x for x in out_def + gone_def if x})[:4]))
            reasons.append(f"Pass rush {d_events:+.2f} sacks+hits per game ({'; '.join(bits) or 'lineup change'})")
        res[app_t] = {"week": next_week.get(t, week), "d_epa_db": round(d_epa, 4), "d_pass_rate": round(d_pass, 4), "d_def_epa_db": round(d_def, 4),
                      "d_pressure_events": round(d_events, 3), "d_int_rate": round(d_int, 4), "d_sack_rate": round(d_sack, 4),
                      "d_rz_td_pct": round(d_rz, 4), "reasons": reasons}
    OUT.write_text(json.dumps({"season": a.season, "week": week, "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                               "teams": res}, indent=1) + "\n")
    for t, v in res.items():
        if v["reasons"]:
            print(t, {k: v[k] for k in ("d_epa_db", "d_pass_rate", "d_def_epa_db", "d_pressure_events")})
            for r in v["reasons"]:
                print("   ", r)


if __name__ == "__main__":
    main()
