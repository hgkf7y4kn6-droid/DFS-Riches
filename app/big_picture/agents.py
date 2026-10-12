"""The NFL Intelligence Desk's research agents.

Frameworks, each doing what it's good at:

* Hugging Face -- Llama (default meta-llama/Llama-3.3-70B-Instruct) served
  through Hugging Face Inference Providers (HF_TOKEN; BIG_PICTURE_MODEL and
  BIG_PICTURE_PROVIDER choose the model and the provider).
* LangChain -- the model interface (langchain-huggingface's ChatHuggingFace),
  and the two non-agent steps: Agent J's review parsed with a JSON output
  parser, and targeted revisions as a prompt | model | parser chain.
* CrewAI -- the desk itself: analysts A-H each work from their own slice of
  the dossier, Agent I (the editor) writes the report from their findings,
  Agent J checks it. CrewAI talks to the LangChain model through LangChainLLM.

Agents never fetch data or do arithmetic: every number they may use is in
the dossier slice they're given, and app.big_picture.qc rejects figures that
aren't. Only run where memory allows (GitHub Actions), never on the web server.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

from crewai import Agent, Crew, Process, Task  # noqa: E402
from crewai.llms.base_llm import BaseLLM  # noqa: E402

DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct"

RULES = """Rules for everything you write:
- Use ONLY facts and numbers from the data you are given. Never invent odds, prices, injuries, statistics,
  ownership, betting splits, sources or timestamps. If something isn't in the data, say it's unavailable.
- Copy numbers exactly as given (no new arithmetic). Probabilities are given as decimals (0.534 = 53.4%).
- Separate observed facts (lines, prices, designations) from estimates (model numbers, projected ownership).
- Opening line = the first DraftKings quote this desk captured; never call it anything else.
- A high total is not proof the over has value; popularity is not proof a line is wrong; low ownership alone
  doesn't make a leverage play. Don't call a move "sharp money" -- no ticket or handle data is connected.
- Be specific and concise. Markdown bullets and short paragraphs. No tables. No preamble."""


# ------------------------------------------------------------------ the model (Hugging Face via LangChain)
def chat_model(max_tokens: int = 1800):
    """Llama through Hugging Face Inference Providers, as a LangChain chat model."""
    from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

    model = os.environ.get("BIG_PICTURE_MODEL") or DEFAULT_MODEL
    endpoint = HuggingFaceEndpoint(
        repo_id=model, task="conversational", provider=os.environ.get("BIG_PICTURE_PROVIDER") or "auto",
        max_new_tokens=max_tokens, temperature=0.2, timeout=240,
        huggingfacehub_api_token=os.environ.get("HF_TOKEN"),
    )
    return ChatHuggingFace(llm=endpoint, model_id=model)


class LangChainLLM(BaseLLM):
    """A CrewAI LLM backed by any LangChain chat model; counts tokens for the run's cost note."""

    chat: Any = None
    usage: dict = {}

    def call(self, messages, tools=None, callbacks=None, available_functions=None, from_task=None,
             from_agent=None, response_model=None) -> str:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        kinds = {"system": SystemMessage, "assistant": AIMessage}
        lc = [kinds.get(m.get("role"), HumanMessage)(content=str(m.get("content") or "")) for m in messages]
        resp = self.chat.invoke(lc)
        meta = getattr(resp, "usage_metadata", None) or {}
        for k in ("input_tokens", "output_tokens"):
            self.usage[k] = self.usage.get(k, 0) + int(meta.get(k) or 0)
        self.usage["calls"] = self.usage.get("calls", 0) + 1
        return resp.content if isinstance(resp.content, str) else str(resp.content)

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False

    def get_context_window_size(self) -> int:
        return 100_000


# ------------------------------------------------------------------ dossier slices
def _j(x) -> str:
    return json.dumps(x, separators=(",", ":"), default=str)


def _cands(g: dict) -> list[dict]:
    keep = ("market", "side", "line", "price", "fair", "points_edge", "model_cond", "model_push", "market_novig",
            "blend_cond", "break_even", "ev_model", "ev_blend", "breakeven_price", "model_breakeven_line", "class", "class_note")
    return [{k: c.get(k) for k in keep if c.get(k) is not None} for c in g["candidates"]]


def slices(d: dict) -> dict[str, str]:
    games = d["games"]
    meta = {k: d["meta"][k] for k in ("season", "week", "generated_et", "definitions", "gaps")}
    cal = d.get("calibration") or {}
    return {
        "A": _j({"meta": meta, "market_status": d["market_status"],
                 "games": [{"game": g["game"], "kickoff": g["kickoff_et"], "market": g["market"], "movement": g["movement"],
                            "summary": g["market_summary"], "fair": {k: g["model"][k] for k in ("fair_home_spread", "fair_total", "home_points", "away_points")},
                            "market_trend": g.get("market_trend")} for g in games]}),
        "B": _j({"meta": meta, "calibration": cal, "league": d["meta"]["league"],
                 "games": [{"game": g["game"], "model": {k: v for k, v in g["model"].items()}, "market": g["market_summary"],
                            "gap": g["model_vs_market"], "teams": g["teams"]} for g in games]}),
        "C": _j({"meta": meta, "games": [{"game": g["game"], "home": g["home"], "away": g["away"], "injuries": g["injuries"],
                                          "key_players": g["key_players"], "trenches": g["trenches"]} for g in games],
                 "role_shifts": d["dfs"]["role_shifts"]}),
        "D": _j({"meta": meta, "games": [{"game": g["game"], "environment": g["environment"], "model": {k: g["model"][k] for k in (
            "home_points", "away_points", "fair_total", "p_shootout", "p_both_24", "p_one_score", "p_blowout")},
            "market": g["market_summary"], "teams": {s: {k: g["teams"][s].get(k) for k in ("team", "plays_pg", "tempo_rank", "pass_rate", "off")}
                                                  for s in ("home", "away")},
            "trenches": g["trenches"], "insights": g["insights"], "weather": g["weather"].get("summary")} for g in games]}),
        "E": _j({"meta": meta, "market_status": d["market_status"], "calibration": cal,
                 "track_record": d.get("track_record"),
                 "games": [{"game": g["game"], "home": g["home"], "away": g["away"], "unresolved_news": g["unresolved_news"],
                            "candidates": _cands(g)} for g in games]}),
        "F": _j({"meta": meta, "dfs": d["dfs"]}),
        "G": _j({"meta": meta, "games": [{"game": g["game"], "environment": {k: g["environment"].get(k) for k in (
            "pop_rank", "pop_share", "env_rank", "ownership_vs_quality", "script")}, "market": g["market_summary"],
            "network": g.get("network"), "window": g.get("window")} for g in games],
                 "chalk": d["dfs"]["chalk"], "chalk_notes": d["dfs"]["chalk_notes"], "fades": d["dfs"]["fades"],
                 "leverage_pairs": d["dfs"]["leverage_pairs"]}),
        "H": _j({"meta": meta, "games": [{"game": g["game"], "kickoff": g["kickoff_et"], "window": g["window"],
                                          "weather": g["weather"]} for g in games]}),
    }


def digest(d: dict, tables: dict) -> str:
    """The compact fact sheet the editor and the reviewer check against."""
    return _j({
        "meta": {k: d["meta"][k] for k in ("season", "week", "generated_et", "games_covered", "definitions", "gaps")},
        "market_status": d["market_status"],
        "dashboard": tables["dashboard"], "changes": d.get("changes"),
        "games": [{"game": g["game"], "kickoff": g["kickoff_et"], "market": g["market_summary"],
                   "model": {k: g["model"][k] for k in ("home_points", "away_points", "fair_home_spread", "fair_total",
                                                       "p_home_win", "p_shootout", "p_both_24", "p_blowout", "spread_se")},
                   "featured": [c for c in _cands(g) if c["class"] != "none"],
                   "injuries": {s: [{k: r.get(k) for k in ("name", "position", "status", "starter", "next_up", "unit")}
                                    for r in g["injuries"][s]] for s in ("home", "away")},
                   "weather": g["weather"].get("summary")} for g in d["games"]],
        "dfs": {k: d["dfs"][k] for k in ("gpp_top", "cash_top", "chalk", "stacks", "leverage", "dst")},
        "track_record": d.get("track_record"),
    })


# ------------------------------------------------------------------ the desk
ANALYSTS = {
    "A": ("Market Intelligence & Line-Movement Analyst",
          "Track DraftKings opening and current spreads, totals, team totals and prices; key-number (3, 7) movement; juice moves "
          "without a number change; whether each move went toward or away from the desk's model.",
          "Ten years on a sportsbook trading desk; distrusts narratives about 'sharp money' without data."),
    "B": ("Quantitative Game Projection Analyst",
          "Explain the independent projections: expected points, fair spread and total, scoring ranges, and how much to trust them "
          "given the standard errors and the backtest.",
          "A forecaster who separates point estimates from confident forecasts and never overreacts to small samples."),
    "C": ("Injury, Personnel & Depth-Chart Analyst",
          "Explain each meaningful designation by football function: who replaces whom, which unit weakens, which teammates gain "
          "a role, and whether it touches quarterback play, protection, pass rush, coverage or run fits.",
          "A former pro scout who reads injuries as matchup consequences, not names; separates Out from Questionable."),
    "D": ("Game Environment & Shootout Analyst",
          "Rank game environments by combined scoring, shootout odds (50+), both teams scoring 24+, and correlated DFS ceiling; "
          "flag high totals with hidden downside.",
          "A film analyst for a DFS research site who explains why a game qualifies instead of labeling it."),
    "E": ("Betting Value & Recommendation Analyst",
          "Present the desk's classified sides: price, fair line, model vs no-vig market probability, blended EV, the price and "
          "number where the edge disappears, the main risk. Say plainly when there's no edge.",
          "A disciplined bettor: price first, conservative thresholds, passes when evidence is thin."),
    "F": ("DFS Ownership, Salary & Leverage Analyst",
          "Identify the best raw-point plays, salary-adjusted values, chalk worth eating, credible low-owned ceilings, leverage and "
          "stacking partners, for cash and tournaments.",
          "A high-stakes DFS player who knows low ownership alone isn't leverage."),
    "G": ("Public Narrative & DFS Popularity Analyst",
          "Identify the games and players the public will favor, whether the matchup supports it, and alternatives with less "
          "ownership; label sentiment as inferred.",
          "A media analyst who separates verified data from inferred sentiment and doesn't fade popular plays by reflex."),
    "H": ("Weather, Scheduling & External Conditions Analyst",
          "Translate kickoff forecasts into football consequences (deep passing, kicking, pace, totals) and flag forecasts too "
          "uncertain to act on; note island and short-week games.",
          "A meteorologist who covers football and refuses blanket weather penalties."),
}
EDITOR = ("Sports Editor & Report Writer",
          "Write the NFL Intelligence Desk report: polished, specific, data-driven, honest about uncertainty, reading like a "
          "professional briefing rather than a set of agent summaries.",
          "A veteran sports-betting journalist; resolves disagreements by naming the assumption behind them.")
REVIEWER = ("Quality Control & Forecast Calibration Analyst",
            "Verify every figure, label and claim in the draft against the fact sheet; flag fabrication, stale or mislabeled "
            "data, contradictions and overconfidence.",
            "The desk's auditor: preserves the record, never lets an estimate pass as a fact.")

EDITOR_GROUPS = [
    ([1, 3, 4], {
        1: "Executive Briefing: 3-5 most important developments, strongest modeled edges (or that there are none), most attractive "
           "environments, key injury uncertainties, what to monitor next. Lead with what's actionable.",
        3: "Best Betting Opportunities: for each strongest/price-sensitive side -- selection and price, why the model disagrees, the "
           "matchup driving it, statistical and personnel evidence, main downside, the price/number where the edge disappears, the "
           "news most likely to change it. Then a separate watchlist. If no meaningful edge exists, say so.",
        4: "Injury & Personnel Impact: by game, then team. Prioritize QB play, offensive line, pass rush, coverage, target "
           "distribution, RB workload and red-zone personnel; who benefits, and role increase vs real efficiency gain.",
    }),
    ([5, 6, 7], {
        5: "Game Environment Rankings: rank for combined scoring, both teams scoring, passing volume, QB and RB ceilings, correlated DFS "
           "production and contrarian stacks; why each qualifies, what derails it, whether the total already prices it.",
        6: "High-Total Traps & Scoring Downside: high totals with fragile outlooks (blowout/pace, defense, drive sustainability, "
           "line/QB vulnerability, weather); the difference between a high-scoring game and an attractive over.",
        7: "Public Betting & DFS Sentiment: games likely to draw attention and ownership, the source of popularity, the verified "
           "numbers, overvalued narratives, alternatives -- sentiment labeled as inferred.",
    }),
    ([8, 9, 10, 12], {
        8: "DFS Matchup & Player Shortlist: QB, RB, WR, TE, DST -- salary, projection and range, role, matchup, team/game totals, "
           "projected ownership, cash suitability, tournament ceiling, stacking partners, injury contingencies.",
        9: "Contrarian Angles & Game Stacks: a few coherent tournament constructions -- game script, correlated players, path to a "
           "big score, ownership where supported, how it fails, bring-backs.",
        10: "What Could Change This Week: a prioritized watchlist (questionable players, line combinations, defensive starters, "
            "backup QBs, weather, line moves, salary/ownership changes, inactives) and what specific development changes what.",
        12: "Closing Summary: the key betting conclusions, the best DFS environments, the top unresolved injury questions, the next "
            "update, and which conclusions remain preliminary.",
    }),
]


def _agent(spec, llm) -> Agent:
    role, goal, backstory = spec
    return Agent(role=role, goal=goal, backstory=backstory, llm=llm, allow_delegation=False, verbose=False, max_iter=2)


def build_crew(d: dict, tables: dict, llm) -> tuple[Crew, dict[str, Task], list[Task], Task]:
    data = slices(d)
    facts = digest(d, tables)
    agents = {k: _agent(spec, llm) for k, spec in ANALYSTS.items()}
    analyst_tasks = {
        k: Task(description=f"{RULES}\n\nYour data (JSON):\n{data[k]}\n\nWrite your findings for the editor: the 5-10 most "
                            "important, specific observations in your area for this week, each tied to the data. Flag anything "
                            "missing that limits your analysis.",
                expected_output="Markdown bullet findings, specific and sourced to the data.", agent=agents[k])
        for k in ANALYSTS
    }
    editor = _agent(EDITOR, llm)
    editor_tasks = []
    for numbers, briefs in EDITOR_GROUPS:
        spec = "\n".join(f"## {n} -- then the section: {brief}" for n, brief in briefs.items())
        editor_tasks.append(Task(
            description=f"{RULES}\n\nFact sheet (JSON) -- the only numbers you may use:\n{facts}\n\nUsing the analysts' findings "
                        f"(in your context) and the fact sheet, write these report sections. Start each with a heading line "
                        f"exactly '## <number>' and nothing else on that line:\n{spec}",
            expected_output="The requested sections, each starting with '## <number>'.", agent=editor,
            context=list(analyst_tasks.values())))
    reviewer = _agent(REVIEWER, llm)
    review_task = Task(
        description=f"{RULES}\n\nFact sheet (JSON):\n{facts}\n\nReview the draft sections in your context against the fact sheet. "
                    "Return ONLY JSON: {\"verdict\": \"pass\" | \"revise\", \"issues\": [{\"section\": <number>, \"problem\": "
                    "\"...\", \"fix\": \"...\"}]}. Flag numbers not in the fact sheet, estimates presented as facts, opening/current "
                    "confusion, recommendations that contradict the classifications, and unsupported certainty.",
        expected_output="JSON with verdict and issues.", agent=reviewer, context=editor_tasks)
    crew = Crew(agents=[*agents.values(), editor, reviewer], tasks=[*analyst_tasks.values(), *editor_tasks, review_task],
                process=Process.sequential, verbose=False)
    return crew, analyst_tasks, editor_tasks, review_task


HEADING = re.compile(r"^\s*#{1,3}\s*(?:section\s*)?(\d{1,2})\b[^\n]*$", re.IGNORECASE | re.MULTILINE)


def split_sections(text: str) -> dict[int, str]:
    marks = list(HEADING.finditer(text or ""))
    out = {}
    for i, m in enumerate(marks):
        n = int(m.group(1))
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)].strip()
        body = re.sub(r"^\s*#{1,3}[^\n]*\n", "", body).strip() if body.startswith("#") else body
        if 1 <= n <= 12 and body:
            out[n] = body
    return out


def parse_review(raw: str) -> dict:
    from langchain_core.output_parsers import JsonOutputParser

    try:
        out = JsonOutputParser().parse(raw)
        if isinstance(out, dict):
            return {"verdict": out.get("verdict") or "pass", "issues": [i for i in out.get("issues") or [] if isinstance(i, dict)]}
    except Exception:
        pass
    return {"verdict": "unparsed", "issues": [], "raw": (raw or "")[:500]}


def revise(chat, sections: dict[int, str], issues: list[dict], facts: str) -> dict[int, str]:
    """One targeted LangChain revision per flagged section (prompt | model | parser)."""
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    chain = ChatPromptTemplate.from_messages([
        ("system", RULES),
        ("human", "Fact sheet (JSON):\n{facts}\n\nSection {n} draft:\n{draft}\n\nReviewer issues:\n{issues}\n\n"
                  "Rewrite the section fixing every issue. Return only the section body, no heading."),
    ]) | chat | StrOutputParser()
    out = {}
    for n in sorted({int(i["section"]) for i in issues if str(i.get("section", "")).isdigit()}):
        if n in sections:
            mine = [i for i in issues if str(i.get("section")) == str(n)]
            out[n] = chain.invoke({"facts": facts, "n": n, "draft": sections[n], "issues": _j(mine)}).strip()
    return out


def run(d: dict, tables: dict, chat=None) -> dict:
    """Run the desk; returns {"sections": {n: markdown}, "notes": {agent: findings}, "review": {...}, "model": ...}."""
    chat = chat or chat_model()
    llm = LangChainLLM(model=os.environ.get("BIG_PICTURE_MODEL") or DEFAULT_MODEL, chat=chat, usage={})
    crew, analyst_tasks, editor_tasks, review_task = build_crew(d, tables, llm)
    crew.kickoff()
    sections: dict[int, str] = {}
    for t in editor_tasks:
        sections.update(split_sections(t.output.raw if t.output else ""))
    review = parse_review(review_task.output.raw if review_task.output else "")
    if review["issues"]:
        sections.update(revise(chat, sections, review["issues"], digest(d, tables)))
        review["revised"] = True
    notes = {k: (t.output.raw if t.output else "") for k, t in analyst_tasks.items()}
    return {"sections": sections, "notes": notes, "review": review,
            "model": f"{llm.model} via Hugging Face ({os.environ.get('BIG_PICTURE_PROVIDER') or 'auto'})",
            "usage": dict(llm.usage)}
