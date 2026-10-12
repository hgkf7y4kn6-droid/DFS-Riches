"""The report's skeleton and the desk's own (template) writing.

build_tables() makes the two tables that are never written by a language
model: the betting-market dashboard (Section 2) and the change log
(Section 11). desk_sections() writes every section straight from the dossier
in plain, numbers-first prose -- the report when no language model is
configured, and the fallback for any section the agents fail to produce.
"""
from __future__ import annotations

SECTIONS = [
    (1, "Executive Briefing"),
    (2, "Betting Market Dashboard"),
    (3, "Best Betting Opportunities"),
    (4, "Injury & Personnel Impact Report"),
    (5, "Game Environment Rankings"),
    (6, "High-Total Traps & Scoring Downside"),
    (7, "Public Betting & DFS Sentiment"),
    (8, "DFS Matchup & Player Shortlist"),
    (9, "Contrarian Angles & Game Stacks"),
    (10, "What Could Change This Week"),
    (11, "Changes Since Yesterday"),
    (12, "Closing Summary"),
]
CLASS_LABEL = {"strongest": "Strongest modeled edge", "price_sensitive": "Smaller / price-sensitive edge",
               "watchlist": "Watchlist pending news", "none": "No current edge"}


# ------------------------------------------------------------------ formatting
def num(x, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    s = f"{x:+g}" if signed else f"{x:g}"
    return s.replace("-", "−")


def price(p) -> str:
    if p is None:
        return "no price"
    return f"+{p}" if p > 0 else f"−{abs(p)}"


def pct(p, digits: int = 0) -> str:
    return "n/a" if p is None else f"{p * 100:.{digits}f}%"


def side_label(g: dict, c: dict) -> str:
    if c["market"] == "spread":
        team = g["home"] if c["side"] == "home" else g["away"]
        return f"{team} {num(c['line'], True)}"
    if c["market"] == "total":
        return f"{c['side'].title()} {num(c['line'])}"
    team = g["home"] if c["market"].endswith("home") else g["away"]
    return f"{team} team total {c['side']} {num(c['line'])}"


def best_side(cands: list[dict], market: str) -> dict | None:
    rows = [c for c in cands if c["market"] == market]
    if not rows:
        return None
    return max(rows, key=lambda c: (c.get("ev_blend") if c.get("ev_blend") is not None else c.get("model_cond", 0) - 1))


# ------------------------------------------------------------------ tables
def dashboard(d: dict) -> list[dict]:
    rows = []
    for g in d["games"]:
        for market, label in (("spread", "Spread"), ("total", "Total"), ("team_total_home", f"{g['home']} TT"),
                              ("team_total_away", f"{g['away']} TT")):
            c = best_side(g["candidates"], market)
            if not c:
                continue
            mv = (g.get("movement") or {}).get({"spread": "spread_home", "total": "total"}.get(market, market))
            q = (g["market"].get(market) or {}).get(c["side"]) or {}
            opening = (q.get("opening") or {})
            fair = c["fair"]
            rows.append({
                "game": g["game"], "market": label, "side": side_label(g, c),
                "opening": f"{num(opening.get('line'), market == 'spread')} ({price(opening.get('price'))})" if opening else "not captured",
                "current": f"{num(c['line'], market == 'spread')} ({price(c.get('price'))})",
                "fair": num(fair, market == "spread"),
                "edge": f"{num(c['points_edge'], True)} pts" + (f", EV {pct(c['ev_blend'], 1)}" if c.get("ev_blend") is not None else ""),
                "status": CLASS_LABEL[c["class"]] if c.get("price_available") else
                ("Model lean, no DraftKings price yet" if c["class"] != "none" else "No price yet"),
                "class": c["class"], "moved": (mv or {}).get("vs_model"),
            })
    order = {"strongest": 0, "price_sensitive": 1, "watchlist": 2, "none": 3}
    rows.sort(key=lambda r: (order[r["class"]], r["game"]))
    return rows


def build_tables(d: dict) -> dict:
    return {"dashboard": dashboard(d), "changelog": (d.get("changes") or {}).get("rows") or []}


# ------------------------------------------------------------------ desk prose
def _featured(d: dict, classes=("strongest", "price_sensitive")) -> list[tuple[dict, dict]]:
    out = [(g, c) for g in d["games"] for c in g["candidates"] if c["class"] in classes]
    out.sort(key=lambda gc: -(gc[1].get("ev_blend") or 0))
    return out


def _bet_block(g: dict, c: dict) -> str:
    lines = [f"**{g['game']} -- {side_label(g, c)} at {price(c.get('price'))}** ({CLASS_LABEL[c['class']]})"]
    lines.append(f"- Model fair number {num(c['fair'], c['kind'] == 'spread')}; posted {num(c['line'], c['kind'] == 'spread')} "
                 f"({num(c['points_edge'], True)} points). Model win probability {pct(c.get('model_cond'), 1)} (pushes excluded), "
                 f"DraftKings no-vig {pct(c.get('market_novig'), 1)}, blended {pct(c.get('blend_cond'), 1)} vs a break-even of "
                 f"{pct(c.get('break_even'), 1)}.")
    if c.get("ev_blend") is not None:
        lines.append(f"- Expected value per unit: {pct(c['ev_model'], 1)} on the model alone, {pct(c['ev_blend'], 1)} blended with the market.")
    if c.get("breakeven_price") is not None:
        lines.append(f"- The edge disappears at a price worse than {price(c['breakeven_price'])}"
                     + (f", or at a number worse than {num(c['model_breakeven_line'], c['kind'] == 'spread')} on the model alone."
                        if c.get("model_breakeven_line") is not None else "."))
    t = g["teams"]
    lines.append(f"- Efficiency: {g['home']} offense {num(t['home']['off'].get('epa_play'))} EPA/play, defense "
                 f"{num(t['home']['def'].get('epa_play'))} allowed; {g['away']} offense {num(t['away']['off'].get('epa_play'))}, "
                 f"defense {num(t['away']['def'].get('epa_play'))} allowed.")
    if g.get("trenches"):
        lines.append(f"- Matchup: {g['trenches'][0]}")
    news = [r for side in ("home", "away") for r in g["injuries"][side] if r["status"] in ("Questionable", "Doubtful")]
    if news:
        lines.append("- News to watch: " + "; ".join(f"{r['name']} ({r['position']}, {r['status']})" for r in news[:4]) + ".")
    return "\n".join(lines)


def injury_line(team: str, r: dict) -> str:
    """One player's cross-checked injury line for Section 4."""
    out = f"{team} {r['position']} {r['name']}: **{r['status']}**"
    if r.get("body_part"):
        out += f" ({r['body_part']})"
    views = ", ".join(f"{src} {v}" for src, v in (r.get("designations") or {}).items() if v and src != "official")
    if r.get("designations", {}).get("official"):
        out += f" -- official team report: {r['designations']['official']}"
    if not r.get("sources_agree", True):
        out += f". Sources differ ({views}): {r.get('status_basis')}"
    elif views:
        out += f" ({views})"
    if r.get("practice"):
        out += ". Practice: " + ", ".join(f"{day} {code}" for day, code in r["practice"].items())
    if r.get("next_up"):
        out += f". Next up: {r['next_up']} ({r.get('next_up_agreement')})"
        from app.big_picture.rosters import _key
        others = {src: n for src, n in (r.get("next_up_by_source") or {}).items() if _key(n) != _key(r["next_up"])}
        if others:
            out += "; " + ", ".join(f"{src} lists {n}" for src, n in others.items())
    if r.get("salary"):
        out += f". DFS ${r['salary']}, proj {num(r.get('proj'))}"
    return out + "."


def desk_sections(d: dict) -> dict[int, str]:
    games = d["games"]
    feat = _featured(d)
    watch = _featured(d, ("watchlist",))
    bt = (d.get("calibration") or {}).get("backtest") or {}
    trusted = (d.get("calibration") or {}).get("trusted") or {}
    by_shoot = sorted(games, key=lambda g: -g["model"]["p_shootout"])
    s: dict[int, str] = {}

    # 1 -- executive briefing
    pts = []
    if not d["market_status"]["available"]:
        pts.append(f"DraftKings Sportsbook prices are unavailable ({d['market_status']['status']}); lines below are the "
                   "nflverse consensus without prices, so no expected value is computed.")
    if feat:
        g, c = feat[0]
        pts.append(f"Top modeled edge: {g['game']} {side_label(g, c)} ({price(c.get('price'))}), blended EV {pct(c.get('ev_blend'), 1)}.")
    else:
        pts.append("No side clears the desk's conservative edge thresholds right now.")
    if by_shoot:
        g = by_shoot[0]
        pts.append(f"Best scoring environment: {g['game']} -- {pct(g['model']['p_shootout'])} chance of {d['meta']['definitions']['shootout']}, "
                   f"model total {num(g['model']['fair_total'])} vs posted {num(g['market_summary']['total'])}.")
    qs = [(g, r) for g in games for side in ("home", "away") for r in g["injuries"][side]
          if r["status"] in ("Questionable", "Doubtful") and (r["position"] == "QB" or r.get("starter"))]
    if qs:
        pts.append("Key injury questions: " + "; ".join(f"{r['name']} ({g[ 'home' if r in g['injuries']['home'] else 'away']}, {r['position']}, {r['status']})"
                                                      for g, r in qs[:4]) + ".")
    if not trusted.get("total", True):
        pts.append(f"Totals are watchlist-only this week: in the backtest the model's totals missed by {bt.get('total_mae_model')} points "
                   f"on average vs {bt.get('total_mae_market')} for the closing line.")
    s[1] = "\n".join(f"- {p}" for p in pts)

    # 2 -- dashboard (the table itself is rendered from data)
    s[2] = ("Every listed DraftKings market, the best side by blended expected value. Opening = the first quote this desk captured. "
            "Fair = the desk model. Blended = model and no-vig market combined "
            f"({d['meta']['definitions']['blend']}).")

    # 3 -- best opportunities
    if feat:
        s[3] = "\n\n".join(_bet_block(g, c) for g, c in feat[:5])
    else:
        s[3] = "No meaningful edge at current prices: no side reaches a positive blended expected value with a real points gap."
    if watch:
        s[3] += "\n\n**Watchlist (not yet actionable)**\n" + "\n".join(
            f"- {g['game']} {side_label(g, c)} ({price(c.get('price'))}): model {pct(c.get('model_cond'), 1)}"
            + (f" -- {c['class_note']}" if c.get("class_note") else
               " -- no DraftKings price to evaluate yet" if not c.get("price_available") else
               " -- unresolved injury news" if g.get("unresolved_news") else " -- the market blend doesn't clear break-even")
            for g, c in watch[:6])

    # 4 -- injuries
    parts = []
    for g in games:
        rows = [(side, r) for side in ("away", "home") for r in g["injuries"][side]]
        if not rows:
            continue
        lines = [f"**{g['game']}**"]
        for side, r in rows[:10]:
            lines.append(f"- {injury_line(g[side], r)}")
        missing = [f"{g[side]} {('official report: ' + c['team_report']) if c.get('team_report') != 'ok' else ''}".strip()
                   for side, c in (g.get("injury_sources") or {}).items() if c.get("team_report") != "ok"]
        if missing:
            lines.append(f"- _Sources: {'; '.join(missing)}._")
        parts.append("\n".join(lines))
    s[4] = ("\n\n".join(parts) or "No designated starters on this week's teams.") + \
        ("\n\nEach designation is cross-checked across Sleeper, ESPN, the team's official injury report and DraftKings; "
         "the next player up across the team's own depth chart, ESPN's and Sleeper's.")

    # 5 -- environments
    lines = []
    for i, g in enumerate(by_shoot[:6], 1):
        m, e = g["model"], g["environment"]
        lines.append(f"{i}. **{g['game']}** -- model {num(m['home_points'])}-{num(m['away_points'])} ({g['home']}-{g['away']}), total "
                     f"{num(m['fair_total'])} vs posted {num(g['market_summary']['total'])}; 50+ points {pct(m['p_shootout'])}, both teams 24+ "
                     f"{pct(m['p_both_24'])}, one-score game {pct(m['p_one_score'])}"
                     + (f"; DFS environment rank #{e['env_rank']}" if e.get("env_rank") else "") + ".")
    s[5] = "\n".join(lines)

    # 6 -- traps
    traps = [g for g in games if (g["market_summary"]["total"] or 0) >= 46 and
             (g["model"]["p_blowout"] >= 0.3 or g["model"]["fair_total"] < (g["market_summary"]["total"] or 0) - 2 or
              (g["weather"].get("severity") in ("poor", "bad")))]
    s[6] = "\n".join(
        f"- **{g['game']}** (total {num(g['market_summary']['total'])}): model total {num(g['model']['fair_total'])}, blowout (17+) "
        f"{pct(g['model']['p_blowout'])}" + (f", weather {g['weather'].get('summary')}" if g['weather'].get('severity') in ('poor', 'bad') else "")
        + ". A high total isn't an over bet unless the price beats the model's number." for g in traps) \
        or "No high total (46+) carries an obvious blowout, weather or efficiency red flag this week."

    # 7 -- sentiment
    pop = sorted([g for g in games if g["environment"].get("pop_share") is not None], key=lambda g: -g["environment"]["pop_share"])
    s[7] = "\n".join(f"- **{g['game']}**: projected {pct(g['environment']['pop_share'])} of DFS ownership"
                     + (f" -- {g['environment']['ownership_vs_quality']}" if g['environment'].get('ownership_vs_quality') else "") + "."
                     for g in pop[:5]) + "\n\nPopularity here is projected from this app's ownership model; no betting-split data is connected."

    # 8 -- shortlist
    dfs = d["dfs"]
    lines = []
    for pos in ("QB", "RB", "WR", "TE"):
        cash, gpp = dfs["cash_top"].get(pos, [])[:2], dfs["gpp_top"].get(pos, [])[:3]
        names = ", ".join(f"{p['name']} (${p['salary']}, {num(p['proj'])} pts, {num(p['own'])}% own)" for p in gpp)
        lines.append(f"- **{pos}** -- GPP: {names}. Cash: " + ", ".join(p["name"] for p in cash) + ".")
    if dfs.get("dst"):
        lines.append("- **DST** -- " + ", ".join(f"{p['name']} (${p['salary']})" for p in dfs["dst"][:3]) + ".")
    s[8] = "\n".join(lines)

    # 9 -- stacks
    s[9] = "\n".join(f"- **{st['team']} ({st['game']})** -- {st['type']}: " + ", ".join(
        f"{p['name']} {p['pos']} ({num(p['own'])}%)" for p in st["players"]) for st in dfs["stacks"][:4]) or "No stacks available."

    # 10 -- watchlist
    items = [f"{r['name']} ({r['position']}, {r['status']}) -- if ruled out, re-price {g['game']}"
             for g, r in qs[:6]]
    items += [f"Weather at {g['game']}: {g['weather'].get('summary')}" for g in games if g["weather"].get("severity") in ("poor", "bad")]
    items += ["DraftKings line moves on the strongest and watchlist sides above", "Final inactives (90 minutes before each kickoff)"]
    s[10] = "\n".join(f"- {x}" for x in items)

    # 11 -- changes
    ch = d.get("changes") or {}
    s[11] = ch.get("note") or f"{len(ch.get('rows') or [])} material changes since {ch.get('since')}; unchanged: {', '.join(ch.get('unchanged') or []) or 'none'}."

    # 12 -- closing
    s[12] = (f"- Betting: {len(feat)} side(s) rated an edge, {len(watch)} on the watchlist.\n"
             f"- DFS environments: {', '.join(g['game'] for g in by_shoot[:3])}.\n"
             f"- Unresolved: {', '.join(r['name'] for _g, r in qs[:4]) or 'no key questionable starters'}.\n"
             "- Next update: the next scheduled run (daily mornings, and Sunday after inactives).\n"
             "- Preliminary: everything tied to questionable players, long-range weather and any line still moving.")
    return s
