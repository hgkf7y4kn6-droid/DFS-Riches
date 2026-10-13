"""One research run: build the dossier, compare with the last report, grade
history, have the agents write (or the desk templates, without a language
model), fact-check, and store a new report version.

    python -m app.big_picture.run [--week N] [--desk-only]

Runs on GitHub Actions (.github/workflows/big-picture.yml), which has the
memory the agent frameworks need; the web server only reads stored reports.
Nothing about the report's content is printed: the repository's Actions
logs are public.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone

from app.big_picture import dossier as dossier_module
from app.big_picture import history, qc, store, writer

log = logging.getLogger("big_picture")

MAX_UNVERIFIED = 3        # more unverified figures than this in an agent-written section: use the desk's version


def title(d: dict) -> str:
    now = datetime.now(dossier_module.ET)
    first = (d.get("changes") or {}).get("first_report")
    if now.weekday() == 6:
        focus = "Final Pregame: Inactives, Weather & Last Prices"
    elif first or now.weekday() in (0, 1):
        focus = "Opening Lines, Market Edges, Injuries & DFS"
    else:
        focus = "Market Moves, Injuries & DFS"
    return f"NFL Intelligence Desk | {now.strftime('%a %b %-d')} | {focus}"


def header(d: dict) -> dict:
    ch = d.get("changes") or {}
    preliminary = bool(ch.get("first_report")) or any(g["unresolved_news"] for g in d["games"])
    rows = ch.get("rows") or []
    return {
        "generated_et": d["meta"]["generated_et"], "timezone": "ET",
        "week": d["meta"]["week"], "season": d["meta"]["season"],
        "games": d["meta"]["games_covered"], "markets": d["meta"]["markets"],
        "status": "Preliminary" if preliminary else "Updated",
        "freshness": [{"source": s["name"], "status": s.get("status"), "captured_at": s.get("captured_at")}
                      for s in d["meta"]["sources"]],
        "gaps": d["meta"]["gaps"],
        "latest_market": [r for r in rows if "line" in r["reason"].lower()][:4],
        "latest_injuries": [r for r in rows if "injury" in r["reason"].lower()][:4],
    }


async def research(season: int | None = None, week: int | None = None, desk_only: bool = False) -> dict:
    t0 = time.time()
    try:        # DraftKings refuses some cloud servers: capture from this runner if the site couldn't
        from app.big_picture import odds
        await odds.snapshot_via_runner(dossier_module.SITE)
    except Exception as exc:
        log.warning("odds snapshot from the runner failed: %s", type(exc).__name__)
    d = await dossier_module.build(season, week)
    season, week = d["meta"]["season"], d["meta"]["week"]
    prev = (await asyncio.to_thread(store.previous_dossiers, season, week, None, 1) or [None])[0]
    d["changes"] = history.changes(d, prev)
    finals = await history.finals_by_week(season, week)
    d["track_record"] = {"backtest": (d.get("calibration") or {}).get("backtest"),
                         "graded": await asyncio.to_thread(history.graded, season, week, finals)}
    tables = writer.build_tables(d)
    desk = writer.desk_sections(d)

    sections, notes, review, model_name, usage = dict(desk), {}, None, None, None
    authors = {n: "desk" for n in desk}
    if not desk_only and os.environ.get("BIG_PICTURE_AGENTS", "1") != "0":
        try:
            from app.big_picture import agents
            out = await asyncio.to_thread(agents.run, d, tables)
            model_name, usage = out.get("model"), out.get("usage")
            usage = {**(usage or {}), "compact": out.get("compact"), "provider_failures": out.get("provider_failures")}
            notes, review = out.get("notes") or {}, out.get("review")
            log.info("agents drafted sections %s", sorted(out.get("sections") or {}))
            for n, text in (out.get("sections") or {}).items():
                if text and text.strip():
                    sections[n], authors[n] = text.strip(), "agents"
        except Exception as exc:          # the desk version stands; say so in the report
            # The provider's error (e.g. auth, model access, context length) -- never report content.
            log.warning("agents failed: %s: %s", type(exc).__name__, str(exc)[:300])
            review = {"verdict": "agents unavailable", "issues": [f"Research agents failed ({type(exc).__name__}); "
                                                                  "this report uses the desk's template writing."]}
    unverified = qc.check_sections(sections, d, tables)
    for n, bad in list(unverified.items()):
        if authors.get(n) == "agents" and len(bad) > MAX_UNVERIFIED:
            log.info("section %d: agent draft had %d unverified figures -- using the desk's version", n, len(bad))
            sections[n], authors[n] = desk[n], "desk (agent draft failed the fact check)"
            unverified.pop(n)
            if (rest := qc.check(desk[n], qc.known_values(d))):
                unverified[n] = rest

    # Metadata only (the repository's logs are public): which sections the agents' drafts survived for.
    for n, _t in writer.SECTIONS:
        log.info("section %d: %s%s", n, authors.get(n, "desk"),
                 f", {len(unverified[n])} unverified figure(s)" if unverified.get(n) else "")
    report = {
        "title": title(d), "header": header(d),
        "writer": "agents" if "agents" in authors.values() else "desk",
        "model": model_name,
        "usage": usage,
        "sections": [{"n": n, "title": t, "markdown": sections.get(n, ""), "author": authors.get(n, "desk"),
                      "unverified": unverified.get(n, [])} for n, t in writer.SECTIONS],
        "tables": tables,
        "qc": {"review": review, "unverified": {str(k): v for k, v in unverified.items()}},
        "agent_notes": notes,
        "elapsed_s": round(time.time() - t0, 1),
    }
    summary = {"title": report["title"], "status": report["header"]["status"], "writer": report["writer"], "model": model_name,
               "edges": sum(1 for r in tables["dashboard"] if r["class"] in ("strongest", "price_sensitive")),
               "games": len(d["games"]), "generated_et": d["meta"]["generated_et"]}
    kind = "agents" if report["writer"] == "agents" else "desk"
    saved = await asyncio.to_thread(store.add_report, season, week, kind, summary, d, report)
    return {**saved, "season": season, "week": week, "kind": kind, "summary": summary, "usage": usage}


def clean_database_url(raw: str | None) -> str | None:
    """The bare postgresql:// URL from a pasted secret, wherever it sits in the pasted text: tolerates quotes,
    whitespace, invisible characters, extra lines and the "psql '...'" / "DATABASE_URL=..." snippet forms."""
    if not raw:
        return raw
    m = re.search(r"postgres(?:ql)?://[^\s'\"]+", raw)
    return m.group(0) if m else raw.strip().strip("'\"").strip()


def describe_secret(value: str) -> str:
    """Harmless facts about a secret's shape for a log line -- never the value or any part of its credentials."""
    scheme = value.split("://", 1)[0] if "://" in value and len(value.split("://", 1)[0]) <= 15 else None
    return (f"length {len(value)}, scheme {scheme or 'none'}, has '@' {'@' in value}, lines {value.count(chr(10)) + 1}, "
            f"mentions neon.tech {'neon.tech' in value}, first character {'letter' if value[:1].isalpha() else repr(value[:1]) if not value[:1].isalnum() else 'digit'}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = clean_database_url(os.environ["DATABASE_URL"])
        if not os.environ["DATABASE_URL"].startswith(("postgresql://", "postgres://")):
            raise SystemExit("DATABASE_URL secret isn't a postgresql:// connection URL -- re-paste it from Render or Neon "
                             f"({describe_secret(os.environ['DATABASE_URL'])})")
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--desk-only", action="store_true")
    a = ap.parse_args()
    out = asyncio.run(research(a.season, a.week, a.desk_only))
    # Only metadata: the report itself stays out of public logs.
    print(f"Stored Big Picture report #{out['id']} ({out['kind']}) for {out['season']} Week {out['week']}: "
          f"{out['summary']['games']} games, {out['summary']['edges']} rated edges, at {out['created_at']}"
          f" ({datetime.now(timezone.utc).isoformat(timespec='seconds')}); written by: {out['summary'].get('model') or 'desk templates'}; "
          f"language model usage: {out.get('usage')}")


if __name__ == "__main__":
    main()
