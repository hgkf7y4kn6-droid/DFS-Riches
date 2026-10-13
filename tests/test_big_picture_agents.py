"""The research crew's wiring, with a scripted stand-in for the language model.

Runs only where the agent frameworks are installed (requirements-agents.txt,
GitHub Actions); the web server's environment skips it."""
import pytest

pytest.importorskip("crewai")
pytest.importorskip("langchain_huggingface")

from langchain_core.language_models.fake_chat_models import FakeListChatModel  # noqa: E402

from app.big_picture import agents, writer  # noqa: E402


def _dossier():
    g = {"game": "NYJ@NE", "home": "NE", "away": "NYJ", "kickoff_et": "Sun 1:00 PM ET", "kickoff_utc": "2026-10-18T17:00:00+00:00",
         "window": "SUN_EARLY", "network": "CBS", "unresolved_news": False,
         "market": {"source": "DraftKings Sportsbook", "prices": True}, "movement": {}, "market_trend": {},
         "market_summary": {"home_spread": -7.0, "total": 43.5}, "model_vs_market": {},
         "model": {"home_points": 26.0, "away_points": 17.0, "fair_home_spread": -9.0, "fair_total": 43.0, "p_home_win": 0.75,
                   "p_shootout": 0.2, "p_both_24": 0.1, "p_one_score": 0.4, "p_blowout": 0.3, "spread_se": 5.0, "inputs": {}},
         "candidates": [{"market": "spread", "side": "home", "kind": "spread", "line": -7.0, "price": -110, "fair": -9.0,
                         "points_edge": 2.0, "class": "strongest", "ev_blend": 0.03, "price_available": True}],
         "injuries": {"home": [], "away": []}, "weather": {"summary": "Dome"}, "environment": {}, "trenches": [],
         "insights": {}, "teams": {"home": {"team": "NE", "off": {}, "def": {}}, "away": {"team": "NYJ", "off": {}, "def": {}}},
         "key_players": {"home": [], "away": []}}
    return {"meta": {"season": 2026, "week": 6, "generated_et": "Mon", "games_covered": ["NYJ@NE"], "definitions": {},
                     "gaps": [], "league": {}},
            "market_status": {"available": True}, "games": [g],
            "dfs": {k: [] for k in ("chalk", "chalk_notes", "stacks", "leverage_pairs", "role_shifts", "dst")} |
                   {"gpp_top": {}, "cash_top": {}, "leverage": {}, "fades": {}},
            "changes": {"first_report": True, "rows": []}, "calibration": {}}


def test_crew_runs_analysts_editor_and_review():
    d = _dossier()
    replies = [f"- {k}: NE -7" for k in "ABCDEFGH"] + [
        "## 1\nBriefing.\n\n## 3\nNE -7.\n\n## 4\nNo injuries.", "## 5\nE.\n## 6\nT.\n## 7\nS.",
        "## 8\nD.\n## 9\nC.\n## 10\nW.\n## 12\nEnd.",
        '{"verdict": "revise", "issues": [{"section": 3, "problem": "thin", "fix": "add the price"}]}', "NE -7 at -110."]
    out = agents.run(d, writer.build_tables(d), chat=FakeListChatModel(responses=replies))
    assert sorted(out["sections"]) == [1, 3, 4, 5, 6, 7, 8, 9, 10, 12]
    assert out["sections"][3] == "NE -7 at -110."            # revised after the review
    assert out["review"]["verdict"] == "revise" and out["review"]["revised"]
    assert set(out["notes"]) == set("ABCDEFGH") and out["usage"]["calls"] == 12


def test_split_sections_and_review_parsing():
    s = agents.split_sections("## 1\nOne.\n\n### Section 3 -- Best bets\nThree.\n## 12\nTwelve.")
    assert s == {1: "One.", 3: "Three.", 12: "Twelve."}
    assert agents.parse_review("not json")["verdict"] == "unparsed"
    assert agents.parse_review('```json\n{"verdict":"pass","issues":[]}\n```')["verdict"] == "pass"


# ------------------------------------------------------------------ provider chain (app.big_picture.llms)
from langchain_core.messages import HumanMessage  # noqa: E402

from app.big_picture import llms  # noqa: E402


@pytest.fixture(autouse=True)
def _no_waits(monkeypatch):
    monkeypatch.setattr(llms, "RATE_LIMIT_WAITS", (0, 0))


class _Broken:
    def invoke(self, *a, **k):
        raise RuntimeError("429 rate limited")


def test_chain_skips_a_failing_provider_for_the_rest_of_the_run():
    built = []
    entries = [("free model", lambda: built.append("free") or _Broken(), False),
               ("local", lambda: built.append("local") or FakeListChatModel(responses=["one", "two"]), True)]
    chain = llms.ProviderChain(entries)
    assert chain.invoke([HumanMessage(content="hi")]).content == "one"
    assert chain.invoke([HumanMessage(content="again")]).content == "two"
    assert built == ["free", "local"]                       # the broken provider is tried once, not per call
    assert chain.used == ["local"] and chain.failures[0].startswith("free model: RuntimeError: 429")


def test_probe_moves_to_the_local_model_when_the_free_tier_is_capped():
    chain = llms.ProviderChain([("free model", _Broken, False), ("local", lambda: FakeListChatModel(responses=["x"]), True)])
    chain.probe()
    assert chain.local and chain.label == "local"


def test_chain_raises_when_everything_fails():
    chain = llms.ProviderChain([("a", _Broken, False)])
    with pytest.raises(RuntimeError, match="every language model provider failed"):
        chain.invoke([HumanMessage(content="hi")])


def test_provider_order(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_MODELS", "a:free, b:free")
    monkeypatch.delenv("BIG_PICTURE_USE_HF", raising=False)
    labels = [label for label, _f, _l in llms.providers()]
    assert labels == ["a:free via OpenRouter (free)", "b:free via OpenRouter (free)",
                      "Llama 3.2 3B on the GitHub runner (llama.cpp)"]
    monkeypatch.setenv("BIG_PICTURE_USE_HF", "1")
    monkeypatch.setenv("HF_TOKEN", "t")
    assert "Hugging Face Inference Providers" in [label for label, _f, _l in llms.providers()]


def test_compact_prompts_for_the_local_model():
    d = _dossier()
    llm = agents.LangChainLLM(model="x", chat=None, usage={})
    _crew, analyst_tasks, _editor, _review = agents.build_crew(d, writer.build_tables(d), llm, compact=True)
    assert all(len(t.description) < agents.LOCAL_SLICE_CHARS + 2000 for t in analyst_tasks.values())


def test_rate_limit_is_retried_before_skipping():
    calls = []

    class Flaky:
        def invoke(self, *a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("Error code: 429 - temporarily rate-limited upstream")
            return FakeListChatModel(responses=["ok"]).invoke("x")

    chain = llms.ProviderChain([("free", Flaky, False), ("local", lambda: FakeListChatModel(responses=["no"]), True)])
    assert chain.invoke([HumanMessage(content="hi")]).content == "ok" and chain.used == ["free"]


def test_local_prompts_are_trimmed_to_fit():
    count = lambda text: len(text) // 4                       # noqa: E731
    msgs = [{"role": "system", "content": "rules " * 50}, {"role": "user", "content": "data " * 20000}]
    out = llms.fit(msgs, 2000, count)
    assert sum(count(m["content"]) for m in out) <= 2000
    assert out[1]["content"].startswith("data ") and "trimmed for the local model" in out[1]["content"]
    assert out[0]["content"] == msgs[0]["content"]            # the short rules message is untouched


def test_split_sections_accepts_small_model_headings_but_not_list_items():
    text = ("**5. Game Environment Rankings**\n1. BUF@LV -- 52.5 total\n2. ARI@LAR\n\n"
            "Section 6: High-Total Traps\nCHI@ATL looks fragile.\n\n7) Public Betting & DFS Sentiment\nARI@LAR draws the public.")
    s = agents.split_sections(text, [5, 6, 7])
    assert set(s) == {5, 6, 7}
    assert s[5].startswith("1. BUF@LV") and "2. ARI@LAR" in s[5]          # the ranking list stays inside section 5
    assert agents.split_sections(text) == {}                              # without expected numbers, only real headings count


def test_split_sections_accepts_title_only_headings():
    text = "**Executive Briefing**\nNo edges today.\n\n### Injury & Personnel Impact Report\nCHI QB Out.\n\nBest Betting Opportunities:\nNone."
    assert agents.split_sections(text, [1, 3, 4]) == {1: "No edges today.", 4: "CHI QB Out.", 3: "None."}
