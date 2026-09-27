const path = require("path");
const L = require(path.join(__dirname, "../../static/lineups.js"));
const assert = require("assert");
const mk = (id, name, team, pos, salary, slot = "") => ({ dk_draftable_id: id, name, team, position: pos, salary, roster_slot: slot, proj_points: 10, game_info: "A@B" });
// showdown pool: each player as CPT (1.5x) and FLEX
const people = [["QB1", "A", "QB", 10000], ["WR1", "A", "WR", 9000], ["RB1", "B", "RB", 8000], ["WR2", "B", "WR", 6000], ["TE1", "A", "TE", 4000], ["K1", "B", "K", 3000], ["WR3", "A", "WR", 2000], ["DST", "B", "DST", 3600]];
let id = 1; const pool = [];
for (const [n, t, p, s] of people) { pool.push(mk(id++, n, t, p, s * 1.5, "CPT")); pool.push(mk(id++, n, t, p, s, "FLEX")); }
let lu = L.emptyLineup("showdown");
let fit = L.fitChecker(lu, "showdown", pool);
assert(pool.filter((p) => fit(p).ok).length === pool.length, "empty lineup: everything fits");
lu = L.addPlayer(lu, "showdown", pool[0]).slots;            // QB1 at captain (15000)
fit = L.fitChecker(lu, "showdown", pool);
assert(fit(pool[0]).ok && fit(pool[0]).reason === "In this lineup");
assert(pool.filter((p) => p.roster_slot === "CPT" && p !== pool[0]).every((p) => !fit(p).ok), "other captains hidden");
assert(!fit(pool[1]).ok && /Already in this lineup/.test(fit(pool[1]).reason), "captain's FLEX row hidden");
assert(fit(pool[3]).ok, "WR1 flex fits");
// fill until salary is tight: 15000 + WR1 9000 + RB1 8000 = 32000; 18000 left for 3 slots, cheapest others: WR3 2000, K1 3000, DST 3600
lu = L.addPlayer(lu, "showdown", pool[3]).slots;
lu = L.addPlayer(lu, "showdown", pool[5]).slots;
fit = L.fitChecker(lu, "showdown", pool);
assert(fit(pool[7]).ok, "WR2 6000 + K1 3000 + WR3 2000 = 11000 <= 18000");
lu = L.addPlayer(lu, "showdown", pool[7]).slots;            // 38000 used, 12000 left for 2 slots
fit = L.fitChecker(lu, "showdown", pool);
assert(fit(pool[9]).ok, "TE1 4000 + WR3 2000 fits");
assert(fit(pool[15]).ok, "DST 3600 + WR3 2000 fits");
const big = mk(99, "Big", "A", "WR", 11000, "FLEX");
assert(!L.fitChecker(lu, "showdown", pool.concat([big]))(big).ok, "11000 + 2000 > 12000");
// classic: filled QB hides other QBs; FLEX still takes RB/WR/TE
const cpool = [mk(1, "Q1", "A", "QB", 7000), mk(2, "Q2", "B", "QB", 6000), mk(3, "R1", "A", "RB", 5000), mk(4, "R2", "B", "RB", 4000), mk(5, "R3", "C", "RB", 4000),
  mk(6, "W1", "A", "WR", 5000), mk(7, "W2", "B", "WR", 4000), mk(8, "W3", "C", "WR", 3500), mk(9, "W4", "D", "WR", 3000), mk(10, "T1", "A", "TE", 3000), mk(11, "D1", "B", "DST", 2500)];
let c = L.addPlayer(L.emptyLineup("classic"), "classic", cpool[0]).slots;
const cf = L.fitChecker(c, "classic", cpool);
assert(!cf(cpool[1]).ok && cf(cpool[1]).reason === "No open slot for this position");
assert(cf(cpool[2]).ok);
console.log("fit tests passed");
// ownership totals in the lineup summary
{
  const a = { ...mk(201, "A1", "A", "QB", 7000), ownership: 20 };
  const b = { ...mk(202, "B1", "B", "RB", 6000), ownership: 5.5 };
  const d = mk(203, "C1", "C", "WR", 5000);          // no ownership yet
  let lu2 = L.emptyLineup("classic");
  for (const p of [a, b, d]) lu2 = L.addPlayer(lu2, "classic", p).slots;
  const s = L.summarize(lu2, "classic");
  assert(s.ownSum === 25.5 && s.ownCount === 2 && s.ownAvg === 12.8, JSON.stringify(s));
  assert(L.summarize(L.emptyLineup("classic"), "classic").ownAvg === null);
  console.log("ownership summary tests passed");
}
