"""How much weight an outside source's DraftKings projections deserve next to the model's, from the weeks graded so far.

    python -m scripts.outside_blend_weights

For each position, the weight w that would have minimised squared error on the graded week for
w * (Fantasy Footballers' projection) + (1 - w) * (model's pre-lock projection), with a bootstrap 80% interval. The projections
used are the ones in data/footballers/w9_source.json against data/footballers/w9_model_snapshot.json, scored against Week 9's
actual DraftKings points (the same 69 players scripts.footballers_compare grade uses).

One week and 10-22 players a position cannot support a full-sized weight, so the weight the model applies is capped at 0.3 and
scaled by the clipped optimum: applied = 0.3 * clip(w_opt, 0, 1). A position where the model beat the source (w_opt <= 0)
gets none. Re-run once more weeks are graded; the cap should come off only when the interval narrows.
Writes data/outside/blend_weights.json.
"""
from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

import numpy as np

from app import nflverse_client as nc
from scripts import footballers_compare as fc

OUT = Path(__file__).resolve().parent.parent / "data" / "outside" / "blend_weights.json"
CAP = 0.3


def w_opt(sub: list[tuple]) -> float:
    s, m, a = (np.array([x[i] for x in sub], dtype=float) for i in (1, 2, 3))
    d = s - m
    return float((d * (a - m)).sum() / (d * d).sum()) if (d * d).sum() else 0.0


async def main() -> None:
    rows, _model, _src = fc.load()
    actuals = await nc.get_week_actuals(2026, 9)
    data = []
    for r in rows:
        if r["proj"] is None or r["m"]["proj"] < 3 or (r["name"], r["pos"]) in fc.BAD_PROJ:
            continue
        a = nc.actual_points(actuals, name=r["m"]["name"], position=r["m"]["pos"], team=r["m"]["team"])
        data.append((r["pos"], r["proj"], r["m"]["proj"], a))
    random.seed(1)
    res = {"basis": "Fantasy Footballers Week 9 projections vs the model's pre-lock projections, scored on Week 9 actuals",
           "cap": CAP, "positions": {}, "weights": {}}
    for pos in ("ALL", "QB", "RB", "WR", "TE", "DST"):
        sub = [x for x in data if pos == "ALL" or x[0] == pos]
        w = w_opt(sub)
        boots = [w_opt([random.choice(sub) for _ in sub]) for _ in range(500)]
        lo, hi = np.percentile(boots, [10, 90])
        rmse = lambda wt: float(np.sqrt(np.mean([(a - (wt * s + (1 - wt) * m)) ** 2 for _p, s, m, a in sub])))      # noqa: E731
        res["positions"][pos] = {"n": len(sub), "w_opt": round(w, 2), "w_80_interval": [round(float(lo), 2), round(float(hi), 2)],
                                 "rmse_model": round(rmse(0), 2), "rmse_source": round(rmse(1), 2), "rmse_half": round(rmse(0.5), 2)}
        if pos != "ALL":
            res["weights"][pos] = round(CAP * min(max(w, 0.0), 1.0), 2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
