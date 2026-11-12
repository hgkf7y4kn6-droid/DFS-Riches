"""Can last season's free FTN participation data stand in for in-season man/zone coverage rates?

    python -m scripts.check_man_rate_prior

Team man rates season to season and early season vs the rest, and the mobile-QB vs man-coverage split
(scripts.test_mobile_qbs) using only the opponent's previous-season man rate. Findings (2023-2025): season-to-season
r = 0.45-0.47, and the league rate moved 41%, 48%, 31%; weeks 1-6 vs 7+ r = 0.68-0.77; with previous-season rates the
mobile-QB edge against man-heavy defenses disappears. So the matchup needs in-season coverage data.
"""
import numpy as np, statistics
from collections import defaultdict
from pathlib import Path
from scripts import test_mobile_qbs as t
d = Path('data/cache/train')
pl = {s: t.plays(d, s) for s in (2023, 2024, 2025)}
def rates(ps, wk=lambda w: True):
    c = defaultdict(lambda: [0, 0])
    for p in ps:
        if p['cov'] and wk(p['week']):
            c[p['defteam']][0] += p['cov'] == 'man'; c[p['defteam']][1] += 1
    return {k: v[0] / v[1] for k, v in c.items() if v[1] > 50}
full = {s: rates(pl[s]) for s in pl}
for a, b in ((2023, 2024), (2024, 2025)):
    ks = sorted(set(full[a]) & set(full[b]))
    print(f'season {a}->{b} team man-rate corr', round(np.corrcoef([full[a][k] for k in ks], [full[b][k] for k in ks])[0, 1], 3))
    # rank by deviation from league
    la, lb = statistics.fmean(full[a].values()), statistics.fmean(full[b].values())
    print('   league', round(la, 3), round(lb, 3), 'MAE of prior (league-adjusted)', round(statistics.fmean(abs((full[a][k]-la)-(full[b][k]-lb)) for k in ks), 3), 'sd of team dev', round(np.std([full[b][k]-lb for k in ks]), 3))
for s in pl:
    e, r = rates(pl[s], lambda w: w <= 6), rates(pl[s], lambda w: w > 6)
    ks = sorted(set(e) & set(r))
    print(s, 'weeks1-6 vs 7+ corr', round(np.corrcoef([e[k] for k in ks], [r[k] for k in ks])[0, 1], 3))
# mobile-QB effect using PRIOR-season man rate only (2024, 2025 games)
out = defaultdict(list)
for s in (2024, 2025):
    rows, _, _ = t.season_rows(d, s, list(range(1, 19)))
    prior = full[s - 1]; lg = statistics.fmean(prior.values())
    st = [r for r in rows if r['pos'] == 'QB' and t.f(r['line'].get('pass_att')) >= 25 and r['arch'] in ('mobile', 'pocket')]
    for r in st:
        r['prior_man'] = prior.get(r['opp'], lg) - lg
    lo, hi = np.quantile([r['prior_man'] for r in st], [1/3, 2/3])
    for r in st:
        g = 'man-heavy' if r['prior_man'] >= hi else 'zone-heavy' if r['prior_man'] <= lo else 'middle'
        out[(r['arch'], g)].append(r)
for k in sorted(out):
    v = out[k]
    print(k, len(v), 'rush yds', round(statistics.fmean(r['rush_yds'] for r in v), 1), 'miss vs proj', round(statistics.fmean(r['actual'] - r['corrected'] for r in v), 2), 'beat', round(statistics.fmean(r['actual'] > r['corrected'] for r in v), 3))
