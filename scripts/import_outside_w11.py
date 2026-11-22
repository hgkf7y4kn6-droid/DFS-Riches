"""Writes data/outside/2026_w11_footballers.json and 2026_w11_sharp.json: the Week 11 outside-source tables, transcribed from
the pasted articles (The Fantasy Footballers' tournament-takes ownership notes and DraftKings optimizer view; Sharp Football's
Worksheet and core / tournament plays). Run `python -m scripts.import_outside_w11` to regenerate.

Footballers records: set "a" = the ownership-notes tables (pOwn and projection, top players per position) and set "b" = the
optimizer view (salary, projection, ceiling, projected ownership, players over $4,000 with a projection). Sharp has no
projection numbers or ownership, only calls: core and tournament plays and role notes, kept as text.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "outside"

# (name, team, pos, pOwn %, projection) -- the ownership-notes tables
SET_A = [
    ("Dak Prescott", "DAL", "QB", 23.43, 23.76), ("Caleb Williams", "CHI", "QB", 13.97, 21.39), ("Cam Ward", "TEN", "QB", 9.20, 18.17),
    ("Josh Allen", "BUF", "QB", 8.09, 23.86), ("Patrick Mahomes", "KC", "QB", 6.41, 20.6), ("Jared Goff", "DET", "QB", 5.43, 18.82),
    ("Justin Herbert", "LAC", "QB", 5.01, 17.07), ("J.J. McCarthy", "NYG", "QB", 3.99, 16.39), ("Trevor Lawrence", "JAX", "QB", 3.78, 19.28),
    ("Bryce Young", "CAR", "QB", 3.69, 17.62), ("Jacoby Brissett", "BAL", "QB", 3.57, 15.83), ("Bo Nix", "DEN", "QB", 3.19, 17.96),
    ("Geno Smith", "NYJ", "QB", 1.94, 15.08),
    ("Emmett Johnson", "KC", "RB", 73.84, 23.95), ("Jonah Coleman", "DEN", "RB", 36.44, 18.9), ("Javonte Williams", "DAL", "RB", 18.90, 18.88),
    ("Jahmyr Gibbs", "DET", "RB", 14.36, 23.96), ("Chuba Hubbard", "CAR", "RB", 13.19, 18.33), ("Tony Pollard", "TEN", "RB", 11.39, 16.39),
    ("James Cook III", "BUF", "RB", 10.41, 18.31), ("Bhayshul Tuten", "JAX", "RB", 10.08, 16.15), ("Cam Skattebo", "NYG", "RB", 9.24, 14.24),
    ("Omarion Hampton", "LAC", "RB", 8.72, 12.67), ("Jaylen Warren", "PIT", "RB", 6.73, 15.48), ("D'Andre Swift", "CHI", "RB", 6.63, 15.58),
    ("Bucky Irving", "TB", "RB", 5.10, 15.67),
    ("CeeDee Lamb", "DAL", "WR", 28.40, 23.01), ("Carnell Tate", "TEN", "WR", 26.32, 15.26), ("George Pickens", "DAL", "WR", 22.86, 16.99),
    ("Elic Ayomanor", "TEN", "WR", 19.63, 10.3), ("Amon-Ra St. Brown", "DET", "WR", 17.46, 20.46), ("Jordyn Tyson", "NO", "WR", 14.54, 13.63),
    ("Rome Odunze", "CHI", "WR", 12.77, 11.17), ("Luther Burden III", "CHI", "WR", 12.67, 14.64), ("Garrett Wilson", "NYJ", "WR", 12.64, 15.6),
    ("Tre' Harris", "LAC", "WR", 11.69, 11.33), ("Parker Washington", "JAX", "WR", 8.99, 14.91), ("Malik Nabers", "NYG", "WR", 8.96, 16.34),
    ("DJ Moore", "BUF", "WR", 8.26, 13.69), ("Rashee Rice", "KC", "WR", 6.86, 13.39), ("Courtland Sutton", "DEN", "WR", 2.98, 9.88),
    ("Colston Loveland", "CHI", "TE", 20.36, 13.28), ("Mark Andrews", "BAL", "TE", 12.19, 9.38), ("Isaiah Likely", "NYG", "TE", 8.39, 13.37),
    ("Cade Otton", "TB", "TE", 8.29, 8.34), ("Dawson Knox", "BUF", "TE", 7.67, 7.3), ("Travis Kelce", "KC", "TE", 7.62, 10.91),
    ("Sam LaPorta", "DET", "TE", 5.87, 9.99), ("Brevyn Spann-Ford", "DAL", "TE", 5.49, 6.91), ("Gunnar Helm", "TEN", "TE", 5.13, 7.55),
    ("Darren Waller", "CAR", "TE", 4.93, 7.93), ("Brenton Strange", "JAX", "TE", 3.94, 8.92), ("Trey McBride", "ARI", "TE", 3.88, 14.0),
    ("Evan Engram", "DEN", "TE", 2.09, 6.65),
    ("Steelers", "PIT", "DST", 14.03, 8.85), ("Chiefs", "KC", "DST", 13.54, 10.34), ("Broncos", "DEN", "DST", 9.96, 9.06),
    ("Chargers", "LAC", "DST", 8.69, 7.5), ("Jets", "NYJ", "DST", 7.21, 6.56), ("Bills", "BUF", "DST", 6.84, 9.22),
    ("Jaguars", "JAX", "DST", 6.30, 7.87), ("Ravens", "BAL", "DST", 4.62, 6.25), ("Bears", "CHI", "DST", 4.21, 7.94),
    ("Panthers", "CAR", "DST", 3.88, 6.55), ("Giants", "NYG", "DST", 3.47, 4.75), ("Lions", "DET", "DST", 2.87, 7.1),
]

# (name, team, pos, salary, projection, ceiling, projected ownership %) -- the optimizer view; zero projections (out) kept as 0
SET_B = [
    ("J. Gibbs", "DET", "RB", 10000, 19.3, 28.09, 13.24), ("K. Walker III", "KC", "RB", 9000, 0.0, 0.0, 14.23),
    ("C. Lamb", "DAL", "WR", 8800, 24.5, 34.85, 28.10), ("A. St. Brown", "DET", "WR", 8200, 17.5, 25.75, 15.07),
    ("J. Cook III", "BUF", "RB", 7900, 25.1, 35.63, 11.61), ("J. Allen", "BUF", "QB", 7700, 22.7, 32.51, 7.95),
    ("C. Hubbard", "CAR", "RB", 7500, 17.6, 25.88, 12.47), ("Z. Flowers", "BAL", "WR", 7400, 16.6, 24.58, 8.32),
    ("J. Williams", "DAL", "RB", 7300, 17.5, 25.75, 18.63), ("B. Bowers", "LV", "TE", 7300, 3.1, 7.03, 0.67),
    ("C. Olave", "NO", "WR", 7200, 16.1, 23.93, 5.15), ("M. Nabers", "NYG", "WR", 7100, 17.2, 25.36, 9.62),
    ("B. Irving", "TB", "RB", 7000, 14.8, 22.24, 3.98), ("D. Swift", "CHI", "RB", 6900, 16.9, 24.97, 6.94),
    ("T. McMillan", "CAR", "WR", 6900, 15.4, 23.02, 5.33), ("G. Pickens", "DAL", "WR", 6800, 18.5, 27.05, 24.20),
    ("B. Tuten", "JAX", "RB", 6800, 15.5, 23.15, 10.35), ("D. Henry", "BAL", "RB", 6700, 13.8, 20.94, 6.04),
    ("D. Prescott", "DAL", "QB", 6700, 26.1, 36.93, 23.88), ("P. Washington", "JAX", "WR", 6700, 16.2, 24.06, 9.72),
    ("T. Lawrence", "JAX", "QB", 6600, 20.4, 29.52, 4.23), ("J. Warren", "PIT", "RB", 6600, 15.1, 22.63, 7.07),
    ("T. McBride", "ARI", "TE", 6600, 13.5, 20.55, 6.03), ("P. Mahomes", "KC", "QB", 6500, 21.9, 31.47, 4.87),
    ("T. Pollard", "TEN", "RB", 6500, 16.8, 24.84, 12.05), ("D. Smith", "PHI", "WR", 6500, 14.8, 22.24, 2.93),
    ("G. Wilson", "NYJ", "WR", 6400, 16.1, 23.93, 12.26), ("C. Williams", "CHI", "QB", 6300, 22.2, 31.86, 13.33),
    ("L. Burden III", "CHI", "WR", 6300, 16.7, 24.71, 13.10), ("J. Coleman", "DEN", "RB", 6300, 18.6, 27.18, 36.27),
    ("S. Barkley", "PHI", "RB", 6100, 11.8, 18.34, 2.39), ("J. Goff", "DET", "QB", 6100, 18.3, 26.79, 5.19),
    ("R. Rice", "KC", "WR", 6100, 15.5, 23.15, 5.85), ("D. Moore", "BUF", "WR", 6000, 15.1, 22.63, 8.08),
    ("E. Johnson", "KC", "RB", 6000, 22.1, 31.73, 64.15), ("B. Hall", "NYJ", "RB", 5900, 13.6, 20.68, 2.91),
    ("J. Williams", "DET", "WR", 5900, 14.2, 21.46, 4.95), ("J. Coker", "CAR", "WR", 5800, 10.4, 16.52, 2.40),
    ("T. Shough", "NO", "QB", 5800, 17.9, 26.27, 3.16), ("C. Skattebo", "NYG", "RB", 5800, 12.6, 19.38, 9.62),
    ("J. Waddle", "DEN", "WR", 5700, 13.9, 21.07, 6.31), ("B. Young", "CAR", "QB", 5700, 17.1, 25.23, 3.16),
    ("I. Likely", "NYG", "TE", 5600, 13.6, 20.68, 10.87), ("B. Nix", "DEN", "QB", 5600, 19.2, 27.96, 4.00),
    ("O. Gordon II", "MIA", "RB", 5600, 11.9, 18.47, 8.43), ("A. Jeanty", "LV", "RB", 5500, 11.8, 18.34, 6.73),
    ("C. Ward", "TEN", "QB", 5500, 23.3, 33.29, 10.12), ("C. Tate", "TEN", "WR", 5500, 16.4, 24.32, 27.29),
    ("A. Rodgers", "PIT", "QB", 5400, 13.2, 20.16, 0.63), ("K. Monangai", "CHI", "RB", 5400, 12.7, 19.51, 1.11),
    ("T. Etienne Jr.", "NO", "RB", 5300, 9.5, 15.35, 0.52), ("B. Mayfield", "TB", "QB", 5300, 10.7, 16.91, 0.64),
    ("D. Metcalf", "PIT", "WR", 5300, 12.3, 18.99, 5.73), ("R. Flournoy", "DAL", "WR", 5300, 14.0, 21.20, 3.95),
    ("J. Brissett", "BAL", "QB", 5200, 14.2, 21.46, 3.84), ("O. Hampton", "LAC", "RB", 5200, 14.4, 21.72, 9.15),
    ("E. Egbuka", "TB", "WR", 5200, 14.1, 21.33, 11.31), ("J. Tyson", "NO", "WR", 5200, 15.2, 22.76, 17.07),
    ("J. Herbert", "LAC", "QB", 5100, 15.9, 23.67, 4.93), ("K. Shakir", "BUF", "WR", 5100, 10.3, 16.39, 2.29),
    ("A. Kamara", "NO", "RB", 5100, 8.3, 13.79, 0.15), ("R. Dowdle", "PIT", "RB", 5100, 10.5, 16.65, 0.88),
    ("J. Downs", "KC", "WR", 5100, 12.8, 19.64, 1.31), ("C. Loveland", "CHI", "TE", 5100, 15.3, 22.89, 20.29),
    ("K. Gainwell", "TB", "RB", 5000, 8.7, 14.31, 0.27), ("L. McConkey", "LAC", "WR", 5000, 6.8, 11.84, 1.33),
    ("F. Mendoza", "LV", "QB", 5000, 10.1, 16.13, 0.39), ("M. Washington Jr.", "LV", "RB", 5000, 6.6, 11.58, 0.11),
    ("T. Johnson", "BUF", "RB", 4900, 7.1, 12.23, 0.11), ("T. Allgeier", "ARI", "RB", 4900, 7.9, 13.27, 0.32),
    ("G. Smith", "NYJ", "QB", 4900, 12.7, 19.51, 1.83), ("B. Allen", "NYJ", "RB", 4900, 9.8, 15.74, 0.37),
    ("M. Washington", "MIA", "WR", 4900, 9.6, 15.48, 1.43), ("A. Mitchell", "NYJ", "WR", 4900, 11.8, 18.34, 5.45),
    ("T. Tucker", "LV", "WR", 4800, 8.9, 14.57, 0.89), ("D. Kincaid", "BUF", "TE", 4800, 3.1, 7.03, 0.04),
    ("J. McCarthy", "NYG", "QB", 4800, 15.3, 22.89, 5.06), ("G. Bernard", "PIT", "WR", 4800, 10.2, 16.26, 1.68),
    ("C. Sutton", "DEN", "WR", 4700, 9.7, 15.61, 3.79), ("T. Kelce", "KC", "TE", 4700, 12.1, 18.73, 7.53),
    ("J. Hill", "BAL", "RB", 4700, 9.0, 14.70, 0.39), ("J. Milton", "PHI", "QB", 4700, 11.7, 18.21, 2.03),
    ("D. Goedert", "PHI", "TE", 4600, 10.0, 16.0, 1.56), ("R. Odunze", "CHI", "WR", 4600, 14.5, 21.85, 15.96),
    ("M. Lemon", "PHI", "WR", 4600, 9.6, 15.48, 0.60), ("J. Meyers", "JAX", "WR", 4500, 11.9, 18.47, 7.76),
    ("K. McCord", "MIA", "QB", 4500, 8.1, 13.53, 0.68), ("S. LaPorta", "DET", "TE", 4400, 11.1, 17.43, 6.97),
    ("C. Douglas", "MIA", "WR", 4400, 11.7, 18.21, 10.59), ("M. Mayer", "LV", "TE", 4300, 10.3, 16.39, 4.41),
    ("C. Godwin Jr.", "TB", "WR", 4200, 8.8, 14.44, 6.57), ("P. Bryant", "DEN", "WR", 4200, 9.4, 15.22, 1.48),
    ("B. Strange", "JAX", "TE", 4100, 10.9, 17.17, 4.32), ("X. Worthy", "KC", "WR", 4100, 8.6, 14.18, 1.27),
    ("Chiefs", "KC", "DST", 4000, 10.7, 16.91, 12.85),
]

# Sharp Football (Rich Hribar), Week 11: (name, team, pos, view, note)
SHARP = [
    ("Dak Prescott", "DAL", "QB", "core", "Trust. Four straight top-10 weeks; Titans allow QB1 weeks in 5 of 6 and are last in pressure rate."),
    ("Patrick Mahomes", "KC", "QB", "core", "Trust. Under center at a career-high rate; Arizona is crushed by play action."),
    ("Cam Ward", "TEN", "QB", "tournament", "Trust. QB4 and QB12 the last two weeks on league-high no-huddle and neutral pace; Dallas is last in passing points allowed."),
    ("Bo Nix", "DEN", "QB", "tournament", "Three straight QB1 weeks; Raiders allow the most passing points over eight weeks."),
    ("Caleb Williams", "CHI", "QB", "note", "QB1 with upside: Bears' highest implied total of his career (30.25)."),
    ("Josh Allen", "BUF", "QB", "note", "Surefire QB1, but his spike weeks come when pushed; a 16.5-point favorite may not push. Pricey to pay for."),
    ("Jared Goff", "DET", "QB", "note", "Fringe QB1 against a Bucs defense that is third in passing points allowed."),
    ("Emmett Johnson", "KC", "RB", "core", "Trust. 87% of snaps, 28 touches, 171 yards last week; Walker held out again."),
    ("Jonah Coleman", "DEN", "RB", "core", "Controls the backfield, ahead of Dobbins on routes (24 to 4); Raiders allow the most yards per touch to backs."),
    ("Tony Pollard", "TEN", "RB", "core", "Trust. Three straight top-10 weeks; 77% of backfield touches with Spears back; Dallas allows the most RB touchdowns (16)."),
    ("James Cook III", "BUF", "RB", "tournament", "Eight straight games with a rushing TD; Miami lost its interior linemen."),
    ("Bucky Irving", "TB", "RB", "tournament", "100 yards and a TD in four of five; run-heavy Bucs, but a road underdog."),
    ("Javonte Williams", "DAL", "RB", "tournament", "League-high 22 opportunities inside the 5; pivot off the Dallas passing game."),
    ("Omarion Hampton", "LAC", "RB", "tournament", "Career-high 22 carries last week; Jets allow 115.8 rushing yards per game to backs (31st)."),
    ("D'Andre Swift", "CHI", "RB", "note", "RB2 if Monangai returns: 72.5% of backfield touches over five games without him, 53% with him."),
    ("Kyle Monangai", "CHI", "RB", "note", "Expected back from the bye; RB2/RB3 line. Both Bears backs depend on touchdowns."),
    ("Jahmyr Gibbs", "DET", "RB", "note", "RB1 with a high ceiling at home, but Tampa is a tough run matchup (third-fewest yards per touch)."),
    ("Chuba Hubbard", "CAR", "RB", "note", "Fringe RB1; Brooks is expected back, which trims his 84% of backfield touches."),
    ("CeeDee Lamb", "DAL", "WR", "core", "Trust. Double-digit targets in five straight; second in the NFL in points against Cover 4."),
    ("Amon-Ra St. Brown", "DET", "WR", "core", "Trust. 20+ PPR points in all four career games against the Bucs; 3.05 yards per route against the blitz."),
    ("Luther Burden III", "CHI", "WR", "core", "WR6-WR8 in four straight; leads the team against Cover 3, which New Orleans plays 42.7% of the time."),
    ("Carnell Tate", "TEN", "WR", "core", "Hopeful he returns; high-end WR2 if he does. Joey Porter Jr. may follow him but teams avoid Porter."),
    ("George Pickens", "DAL", "WR", "tournament", "Trust. 11-145-3 last week; Titans are flooded by outside receivers."),
    ("Malik Nabers", "NYG", "WR", "tournament", "28.9% target share and 2.58 yards per route with McCarthy; fringe WR1."),
    ("Garrett Wilson", "NYJ", "WR", "tournament", "35-39% target shares the last two games; Cooper out; Chargers 28th in points per target allowed."),
    ("Elic Ayomanor", "TEN", "WR", "tournament", "90.7% route rate, 27% of targets; WR3/FLEX with end-zone targets."),
    ("Ja'Kobi Lane", "BAL", "WR", "tournament", "11 targets last week; 42.9% of his red-zone routes targeted."),
    ("Jordyn Tyson", "NO", "WR", "note", "WR3: route rate jumped from 35% to 72%, 41.9% targeted per route, but air yards per target only 5.3."),
    ("Chris Olave", "NO", "WR", "note", "WR2 rather than a locked WR1: target share fell to 12% last week with Tyson soaking up short targets."),
    ("Rome Odunze", "CHI", "WR", "note", "Upside WR2/WR3 as the Bears' third target; 35.7% air-yard share."),
    ("Colston Loveland", "CHI", "TE", "core", "TE5 in expected points since Williams returned; 25.8% of the targets over four games."),
    ("Mark Andrews", "BAL", "TE", "core", "8-8-82 with Brissett; fringe TE1, but the target jump needs to stick."),
    ("Mason Taylor", "NYJ", "TE", "tournament", "Chargers allow a league-high 9.3 yards per target to tight ends; Cooper and Williams out."),
    ("Kenyon Sadiq", "NYJ", "TE", "tournament", "Preferred over Taylor: more slot work and a 20.6% target rate per route."),
    ("Dawson Knox", "BUF", "TE", "tournament", "Kincaid doubtful; Miami allows an 83.3% catch rate to tight ends."),
    ("Gunnar Helm", "TEN", "TE", "tournament", "Cheap attachment to the most popular game; only 51% of dropbacks, so a matchup TE2."),
    ("Isaiah Likely", "NYG", "TE", "note", "TE1, but a tougher ceiling spot: the Jaguars allow the fewest yards per target to tight ends."),
    ("Trey McBride", "ARI", "TE", "note", "Floor-based TE1: route count fell to 20; the ceiling is lowered by the quarterback change."),
    ("Brock Bowers", "LV", "TE", "note", "Left last week's game after 11 snaps and is expected to miss time."),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    foot = {
        "_readme": __doc__, "source": "The Fantasy Footballers", "season": 2026, "week": 11, "slate": "classic_sunday",
        "records": ([{"set": "a", "name": n, "team": t, "pos": p, "own": o, "proj": pr} for n, t, p, o, pr in SET_A]
                    + [{"set": "b", "name": n, "team": t, "pos": p, "salary": s, "proj": pr, "ceil": c, "own": o}
                       for n, t, p, s, pr, c, o in SET_B]),
    }
    (OUT / "2026_w11_footballers.json").write_text(json.dumps(foot, indent=1) + "\n")
    sharp = {"_readme": __doc__, "source": "Sharp Football", "season": 2026, "week": 11, "slate": "classic_sunday",
             "notes": [{"name": n, "team": t, "pos": p, "view": v, "note": x} for n, t, p, v, x in SHARP]}
    (OUT / "2026_w11_sharp.json").write_text(json.dumps(sharp, indent=1) + "\n")
    print(len(foot["records"]), "Footballers records;", len(sharp["notes"]), "Sharp notes")


if __name__ == "__main__":
    main()
