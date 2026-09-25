(function () {
  "use strict";

  const panelEl = document.getElementById("dm-panel");
  const slateEl = document.getElementById("dm-slate");
  const asofEl = document.getElementById("dm-asof");
  const weekEl = document.getElementById("dm-week");
  const tabs = Array.from(document.querySelectorAll(".dm-tabs [role=tab]"));
  const TAB_KEY = "dfsriches:dfsModelTab";

  const state = { season: null, week: null, slate: null, data: null, tab: "summary",
                  tableSort: { key: "final", dir: -1 }, tablePos: "ALL", tableQuery: "", poolPos: "QB",
                  contest: "gpp", contestSize: null };
  try { state.tab = localStorage.getItem(TAB_KEY) || "summary"; } catch (e) { /* private mode */ }

  const esc = DFS.esc;
  const num = (v, d) => (v == null ? "-" : Number(v).toFixed(d == null ? 1 : d));
  const pct = (v) => (v == null ? "-" : Math.round(v * 100) + "%");
  const money = DFS.money;
  const spread = (s) => (s == null ? "-" : s === 0 ? "PK" : (s > 0 ? "+" : "") + s);
  const INJ = { Q: "Q", D: "D", O: "OUT", IR: "IR" };

  // --------------------------------------------------------------- badges
  function popBadge(p) {
    if (p.ownership != null) return `<span class="dm-own-pct" title="Bayesian posterior ownership (large-field GPP mean). Intervals and confidence: Ownership tab">${num(p.ownership, 1)}%</span>`;
    if (!p.popularity) return '<span class="dm-muted" title="No ownership data">-</span>';
    return `<span class="dm-pop dm-pop-${p.popularity.toLowerCase()}" title="Popularity estimate from value and projection rank at the position -- not ownership data">est. ${esc(p.popularity)}</span>`;
  }
  function uncBadge(p) {
    if (!p.uncertainty_label) return "";
    const tip = (p.uncertainty_reasons || []).join("; ") || "Outcome range at the position";
    return `<span class="dm-unc dm-unc-${p.uncertainty_label.toLowerCase()}" title="Projection uncertainty. ${esc(tip)}">${esc(p.uncertainty_label)}</span>`;
  }
  function injBadge(p) {
    return p.injury && p.injury !== "Healthy" ? `<span class="dm-inj" title="DraftKings injury status">${esc(INJ[p.injury] || p.injury)}</span>` : "";
  }
  const card = (title, body, cls) => `<section class="dm-card${cls ? " " + cls : ""}"><h3>${title}</h3>${body}</section>`;
  const note = (t) => (t ? `<p class="dm-note">${esc(t)}</p>` : "");
  const bullets = (items) => (items && items.length ? `<ul class="dm-bullets">${items.map((i) => `<li>${i}</li>`).join("")}</ul>` : '<p class="dm-muted">None.</p>');

  function playerHead(c) {
    return `<div class="dm-li-top">
        <span class="tp-pos">${esc(c.position)}</span>
        <span class="dm-name">${esc(c.name)}</span>${injBadge(c)}
        <span class="dm-team">${esc(c.team)}${c.opponent ? " v " + esc(c.opponent) : ""}</span>
        <span class="dm-sal">${money(c.salary)}</span>
      </div>
      <div class="dm-li-nums">
        <span title="Final projection (consensus + adjustments)">Proj <b>${num(c.final)}</b></span>
        <span title="Floor (15th percentile)">Floor ${num(c.floor)}</span>
        <span title="Ceiling (85th percentile)">Ceil ${num(c.ceiling)}</span>
        <span title="Points per $1,000 of salary">${num(c.value, 2)}/$1k</span>
        ${popBadge(c)} ${uncBadge(c)}
      </div>`;
  }

  function playerList(title, cards, opts) {
    opts = opts || {};
    if (!cards || cards.length === 0) return card(esc(title), `<p class="dm-muted">${esc(opts.empty || "None this week.")}</p>`, opts.cls);
    const items = cards.map((c) => `<li>${playerHead(c)}
        ${c.reason ? `<div class="dm-reason">${esc(c.reason)}</div>` : ""}
        ${c.reasons ? `<ul class="dm-reasons">${c.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
      </li>`).join("");
    return card(esc(title), note(opts.note) + `<ol class="dm-list">${items}</ol>`, opts.cls);
  }

  // --- metric chips for position pools
  // Trench matchup edge (league z-score gap); positive favors this player.
  function edge(v) { return (v > 0 ? "+" : "") + num(v, 1); }
  const METRIC_LABELS = {
    proj_rush_yd: ["Proj rush yds", (v) => num(v, 0)], rush_share: ["Rush share of proj", pct], ypa: ["YPA (L4)", (v) => num(v, 1)],
    td_rate: ["TD rate", pct], pass_att_l4: ["Pass att/g", (v) => num(v, 1)], implied: ["Implied", (v) => num(v, 1)],
    spread: ["Spread", spread], total: ["Total", (v) => num(v, 1)], concentration: ["Top-2 target share", pct],
    proj_carries: ["Proj carries", (v) => num(v, 1)], proj_targets: ["Proj targets", (v) => num(v, 1)], proj_rec: ["Proj rec", (v) => num(v, 1)],
    proj_opps: ["Proj opportunities", (v) => num(v, 1)], proj_tds: ["Proj TDs", (v) => num(v, 2)], targets_l4: ["Targets/g", (v) => num(v, 1)],
    target_share: ["Target share", pct], air_yards_share: ["Air yards share", pct], adot: ["aDOT", (v) => num(v, 1)],
    carries_l4: ["Carries/g", (v) => num(v, 1)], carry_share: ["Carry share", pct], matchup: ["Matchup adj", (v) => "x" + num(v, 2)],
    pass_rate_rank: ["Neutral pass rate rank", (v) => "#" + v], proj_sacks: ["Proj sacks", (v) => num(v, 1)],
    proj_takeaways: ["Proj takeaways", (v) => num(v, 1)], opp_implied: ["Opp implied", (v) => num(v, 1)],
    opp_sacks_taken: ["Opp sacks taken/g", (v) => num(v, 1)], opp_giveaways: ["Opp giveaways/g", (v) => num(v, 1)],
    pass_edge: ["Pass matchup", edge], protection_edge: ["Protection vs rush", edge], run_edge: ["Run matchup", edge],
    pressure_edge: ["Pressure edge", edge],
  };
  function metrics(m) {
    if (!m) return "";
    const chips = Object.entries(METRIC_LABELS).filter(([k]) => m[k] != null && m[k] !== "").map(([k, [label, fmt]]) =>
      `<span class="dm-chip-static"><span class="dm-muted">${label}</span> ${esc(fmt(m[k]))}</span>`);
    if (m.stack_partners && m.stack_partners.length) chips.push(`<span class="dm-chip-static"><span class="dm-muted">Stack with</span> ${esc(m.stack_partners.join(", "))}</span>`);
    if (m.games != null) chips.push(`<span class="dm-chip-static dm-muted">usage: last ${m.games} games${m.this_season_games < 2 ? " (incl. last season)" : ""}</span>`);
    return `<div class="dm-chips">${chips.join("")}</div>`;
  }
  function poolList(title, cards, opts) {
    opts = opts || {};
    if (!cards || !cards.length) return card(esc(title), `<p class="dm-muted">${esc(opts.empty || "No qualifying players.")}</p>`);
    return card(esc(title), note(opts.note) + `<ol class="dm-list">${cards.map((c) => `<li>${playerHead(c)}${metrics(c.metrics)}
      ${(c.reasons || []).length ? `<ul class="dm-reasons">${c.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}</li>`).join("")}</ol>`);
  }

  function stackList(title, stacks, opts) {
    opts = opts || {};
    if (!stacks || stacks.length === 0) return card(esc(title), '<p class="dm-muted">No stack with a playable QB and pass catcher.</p>', opts.cls);
    const items = stacks.map((s) => `
      <li>
        <div class="dm-li-top"><span class="dm-name">${esc(s.team)}: ${esc(s.type)}</span><span class="dm-sal">${money(s.salary)}</span></div>
        <div class="dm-stack-players">${s.players.map((p) => `<span><span class="tp-pos">${esc(p.position)}</span> ${esc(p.name)} ${popBadge(p)}</span>`).join("")}</div>
        <div class="dm-li-nums"><span>Proj <b>${num(s.final)}</b></span><span>Ceil ${num(s.ceiling)}</span><span title="Stack ceiling minus 3.5x its salary in $1k, plus game environment">Score ${num(s.score)}</span></div>
        <div class="dm-reason">${esc(s.reason)}</div>
        ${s.bring_back_note ? `<div class="dm-reason dm-muted">Bring-back: ${esc(s.bring_back_note)}</div>` : ""}
      </li>`).join("");
    return card(esc(title), `<ol class="dm-list">${items}</ol>`, opts.cls);
  }

  function newsList(items) {
    if (!items || items.length === 0) return card("Biggest news &amp; context changes", '<p class="dm-muted">No injuries or model adjustments of note.</p>');
    return card("Biggest news &amp; context changes", `<ol class="dm-list">${items.map((n) => `
      <li><div class="dm-li-top"><span class="dm-tag dm-tag-${esc(n.kind)}">${n.kind === "model" ? "Model" : "Sourced"}</span><span class="dm-muted">${esc(n.source)}</span></div>
      <div class="dm-reason">${esc(n.text)}</div></li>`).join("")}</ol>`);
  }

  function constructionList(items) {
    if (!items || items.length === 0) return "";
    return card("GPP lineup constructions", `<ol class="dm-list">${items.map((c) => `
      <li><div class="dm-li-top"><span class="dm-name">${esc(c.name)}</span><span class="dm-muted">${esc(c.lineup)}</span></div>
      <div class="dm-reason">${esc(c.idea)}</div></li>`).join("")}</ol>`);
  }

  // ------------------------------------------------------------ Summary
  function renderSummary(d) {
    const s = d.summary;
    const ownNote = "Ownership = Bayesian posterior mean (see the Ownership tab for intervals and confidence).";
    const rec = d.lineups.cash[0];
    return `<div class="dm-grid">
      ${rec ? card("Recommended cash lineup", lineupMini(rec) + `<button type="button" class="dm-link" data-goto="cash">Full cash breakdown →</button>`) : ""}
      ${card("Top GPP lineups by quality", (d.lineups.gpp.slice().sort((a, b) => b.eval.quality - a.eval.quality).slice(0, 3)
        .map((lu) => `<div class="dm-mini-head"><b>${esc(lu.label)}</b> <span class="dm-muted">${esc(lu.construction)}</span> <span class="dm-q">Q ${num(lu.eval.quality, 0)}</span></div><p class="dm-reason">${esc(lu.eval.win_scenario)}</p>`).join("")
        || '<p class="dm-muted">None built.</p>') + `<button type="button" class="dm-link" data-goto="gpp">All GPP lineups →</button>`)}
      ${playerList("Top 10 final projections", s.top_projections)}
      ${playerList("10 best values", s.best_values, { note: "Pts per $1k vs the position's median (raw value always favors QBs)." })}
      ${playerList("10 highest ceilings", s.highest_ceilings)}
      ${playerList("10 best leverage plays", s.leverage, { note: ownNote })}
      ${stackList("5 strongest stacks", s.stacks)}
      ${playerList("10 most uncertain projections", s.most_uncertain)}
      ${newsList(s.news)}
      ${constructionList(s.constructions)}
    </div>`;
  }

  // -------------------------------------------------------------- Slate
  function gameTable(games) {
    const rows = games.map((g) => `<tr>
      <th scope="row">${esc(g.game)}<div class="dm-muted">${esc(g.kickoff || "")}</div></th>
      <td class="num">${num(g.env_score, 2)}<div class="dm-muted">#${g.env_rank}</div></td>
      <td class="num">${num(g.total)}</td>
      <td class="num">${esc(g.home)} ${spread(g.spread_home)}</td>
      <td class="num">${esc(g.away)} ${num(g.away_implied)} / ${esc(g.home)} ${num(g.home_implied)}</td>
      <td class="num">${pct(g.pop_share)}<div class="dm-muted">#${g.pop_rank}</div></td>
      <td>${[g.shootout ? '<span class="dm-tag dm-tag-sourced">Shootout</span>' : "", g.negative_script ? '<span class="dm-tag">Script risk</span>' : "",
             g.live_dog ? '<span class="dm-tag">Live dog</span>' : "", g.popular ? '<span class="dm-pop dm-pop-high">Popular</span>' : "",
             g.leverage_game ? '<span class="dm-tag dm-tag-model">Leverage</span>' : ""].join(" ")}
        <div class="dm-reason">${esc(g.script)}</div>${(g.trench_notes || []).map((n) => `<div class="dm-reason">${esc(n)}</div>`).join("")}<div class="dm-muted">${esc(g.ownership_vs_quality)}</div></td>
    </tr>`).join("");
    return `<div class="dm-table-wrap"><table class="dm-table"><thead><tr><th scope="col">Game</th><th scope="col" title="Weighted z-score: total 40%, closeness of spread 20%, top-10 ceiling 20%, neutral tempo 10%, pass rate 10%">Environment</th><th scope="col">Total</th><th scope="col">Spread</th><th scope="col">Implied</th><th scope="col" title="Share of the slate's popularity (ownership, or the estimate)">Popularity</th><th scope="col">Script</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function renderSlate(d) {
    const st = d.strategy, o = st.overview;
    const inj = o.injuries.map((i) => `<li><b>${esc(i.player)}</b> (${esc(i.team)} ${esc(i.position)}) ${esc(INJ[i.status] || i.status)} -- ${num(i.season_fppg)} DK pts/g this season
      ${i.impact.length ? `<div class="dm-muted">Opportunity for: ${i.impact.map((c) => `${esc(c.name)} (${esc(c.reason)})`).join("; ")}</div>` : ""}</li>`);
    return `${card("Game environments", note("Don't assume the highest total is the best stack: the environment score blends total, spread, ceiling, pace and pass rate, and popularity shows whether the field agrees. Sourced: nflverse closing lines, neutral tempo/pass rate. Popularity: " + o.popularity_note + ".") + gameTable(st.games), "dm-wide")}
      <div class="dm-grid">
        ${card("Highest implied team totals", bullets(o.top_implied.map((t) => `<b>${esc(t.team)}</b> ${num(t.implied)} vs ${esc(t.opponent)} (${spread(t.spread)})`)))}
        ${card("Highest game totals", bullets(o.top_totals.map((g) => `<b>${esc(g.game)}</b> ${num(g.total)}`)))}
        ${card("Shootout potential", bullets(o.shootouts.map(esc)))}
        ${card("Potential negative game scripts", bullets(o.negative_scripts.map((g) => `<b>${esc(g.game)}</b>: ${esc(g.script)}`)))}
        ${card("Heavy favorites / live underdogs", bullets(o.heavy_favorites.map((t) => `<b>${esc(t.team)}</b> ${spread(t.spread)} vs ${esc(t.opponent)}`)
            .concat(o.live_underdogs.map((t) => `Live dog: <b>${esc(t.team)}</b> implied ${num(t.implied)} (${esc(t.game)})`))))}
        ${card("Games the field will like vs leverage games", bullets(o.popular_games.map((g) => `Popular: <b>${esc(g.game)}</b> -- ${esc(g.note)}`)
            .concat(o.leverage_games.map((g) => `Leverage: <b>${esc(g.game)}</b> -- ${esc(g.note)}`))))}
        ${card("Significant injuries and who gains", inj.length ? `<ul class="dm-bullets">${inj.join("")}</ul>` : '<p class="dm-muted">None of note (DraftKings statuses).</p>')}
        ${playerList("Cheap players whose roles changed", o.cheap_role_changes, { empty: "No injury-driven role changes at cheap salaries." })}
        ${playerList("Best QB environments", o.best_qb.map((c) => ({ ...c, reason: (c.reasons || []).join("; ") })))}
        ${playerList("Best RB situations (volume)", o.best_rb.map((c) => ({ ...c, reason: (c.reasons || []).join("; ") })))}
        ${card("Best WR environments", bullets(o.best_wr_teams.map((t) => `<b>${esc(t.team)}</b>: implied ${num(t.implied)}, top-2 target share ${pct(t.concentration)}, neutral pass rate #${t.pass_rate_rank || "-"}`)))}
        ${card("TE approach", `<p><b>${esc(o.te_approach.strategy)}</b></p>${note(o.te_approach.why)}<button type="button" class="dm-link" data-goto="pools" data-pos="TE">TE options →</button>`)}
        ${playerList("Salary-saving plays", o.salary_savers, { note: "Cheap players with a real projected role -- never just cheap." })}
        ${playerList("Major chalk", o.chalk.map((c) => ({ ...c, reason: `${c.classification}: ${c.why_popular}` })))}
        ${playerList("Low-owned ceiling plays", o.low_owned_ceiling)}
      </div>`;
  }

  // -------------------------------------------------------------- Pools
  function renderPools(d) {
    const P = d.strategy.pools;
    const posBtns = ["QB", "RB", "WR", "TE", "DST", "GPP pool"].map((p) => `<button type="button" class="dm-chip" data-poolpos="${p}" aria-pressed="${state.poolPos === p}">${p}</button>`).join("");
    let body = "";
    if (state.poolPos === "QB") {
      body = poolList("GPP QB pool", P.QB.gpp, { note: "Ceiling first, plus rushing upside (extra paths to a ceiling game), stack partners and game environment." })
        + poolList("Cash QB pool", P.QB.cash, { note: "Stable projection + floor." })
        + poolList("Naked-QB candidates", P.QB.naked_candidates, { note: "Only QBs whose rushing is a quarter or more of their projection -- they can reach a ceiling without a pass catcher.", empty: "No QB with enough rushing upside to play naked." });
    } else if (state.poolPos === "RB") {
      body = poolList("Cash RB pool", P.RB.cash, { note: "Predictable workload: carries, receiving role, positive script. Cheap RBs need real volume." })
        + poolList("GPP RB pool", P.RB.gpp, { note: "Ceiling, touches and TD equity. Chalk RBs aren't auto-faded -- see how each can fail on Chalk & Leverage." });
    } else if (state.poolPos === "WR") {
      body = poolList("Cash WR pool", P.WR.cash, { note: "Predictable target volume." })
        + poolList("GPP WR pool", P.WR.gpp, { note: "Volatility welcome: ceiling, air-yards share, targets. Elite WRs aren't faded for a cornerback matchup (no CB data is used)." });
    } else if (state.poolPos === "TE") {
      body = card("Recommended TE approach", `<p><b>${esc(P.TE.recommendation.strategy)}</b></p>${note(P.TE.recommendation.why)}`)
        + playerList("Strategy A: pay up", P.TE.pay_up, { empty: "No elite TE worth the salary." })
        + playerList("Strategy B: punt", P.TE.punt, { empty: "No cheap TE with a real target role." })
        + playerList("Mid-range TEs to fade in GPPs", P.TE.mid_fades, { empty: "No popular mid-range TE without a ceiling edge." });
    } else if (state.poolPos === "DST") {
      body = poolList("DST pool", P.DST, { note: "Sack and turnover potential, opponent implied total, script (favorites force dropbacks), and how often the opponent takes sacks / gives it away." });
    } else {
      const G = d.strategy.gpp_pool;
      body = playerList("Core plays", G.core) + playerList("Chalk", G.chalk.map((c) => ({ ...c, reason: `${c.classification}: ${c.why_popular}` })))
        + playerList("Leverage plays", G.leverage) + playerList("Low-owned ceiling plays", G.low_owned_ceiling)
        + playerList("Salary-saving plays", G.salary_savers);
    }
    return `<div class="dm-table-tools">${posBtns}</div><div class="dm-grid">${body}</div>`;
  }

  // ---------------------------------------------------- Chalk & Leverage
  function renderChalk(d) {
    const st = d.strategy;
    const rows = st.chalk.map((c) => `<tr>
      <th scope="row">${esc(c.name)} ${injBadge(c)}<div class="dm-muted">${esc(c.team)} v ${esc(c.opponent)}</div></th>
      <td>${esc(c.position)}</td><td class="num">${money(c.salary)}</td><td class="num">${num(c.final)}</td><td class="num">${num(c.ceiling)}</td>
      <td class="num">${popBadge(c)}</td><td>${esc(c.why_popular)}</td><td>${esc(c.risk)}</td>
      <td><span class="dm-class dm-class-${esc(c.classification.split(" ")[0].toLowerCase())}">${esc(c.classification)}</span></td></tr>`).join("");
    const L = st.leverage;
    return card("Chalk", note("Chalk = 15%+ Bayesian posterior ownership (large-field GPP)."
        + " For each: why the field will play him, how he can fail, and what to do with him. Chalk isn't faded just for being popular.")
        + `<div class="dm-table-wrap"><table class="dm-table"><thead><tr><th scope="col">Player</th><th scope="col">Pos</th><th scope="col">Salary</th><th scope="col">Proj</th><th scope="col">Ceiling</th><th scope="col">Own</th><th scope="col">Why popular?</th><th scope="col">How he fails</th><th scope="col">Classification</th></tr></thead><tbody>${rows || '<tr><td colspan="9" class="dm-muted">No chalk identified.</td></tr>'}</tbody></table></div>`, "dm-wide")
      + `<div class="dm-grid">
        ${playerList("Player-vs-player leverage", L.player_vs_player, { note: "A lower-owned RB from the same game as a chalk RB with a comparable ceiling.", empty: "No same-game RB with a comparable ceiling." })}
        ${playerList("Same-team leverage", L.same_team, { note: "Teammates whose big game usually means the chalk player's wasn't.", empty: "None." })}
        ${playerList("Salary leverage", L.salary, { note: "Cheaper players at the same position with most of an expensive chalk player's ceiling.", empty: "None." })}
        ${card("Game leverage", L.game.length ? bullets(L.game.map((g) => `<b>${esc(g.game)}</b>: ${esc(g.reason)}<div class="dm-muted">${esc(g.script)}</div>`)) : '<p class="dm-muted">The field is spread across the good games this week.</p>')}
        ${playerList("Ownership leverage", L.ownership, { note: "Lower-owned players with a top-40% ceiling and a real role. Meaningful leverage, not random contrarian plays." })}
      </div>`;
  }

  // -------------------------------------------------------------- Stacks
  function renderStacks(d) {
    const st = d.strategy;
    const byGame = {};
    for (const s of st.stacks) (byGame[s.game] = byGame[s.game] || []).push(s);
    return card("Game environments", gameTable(st.games), "dm-wide")
      + `<div class="dm-grid">${stackList("Strongest stacks on the slate", st.stacks.slice(0, 6))}
        ${st.games.map((g) => (byGame[g.game] || []).length ? stackList(`${g.game} stacks`, byGame[g.game].slice(0, 4)) : "").join("")}</div>`;
  }

  // ------------------------------------------------------------- Lineups
  function lineupTable(lu, withReason) {
    const rows = lu.players.map((p) => `<tr><td>${esc(p.slot)}</td><th scope="row">${esc(p.name)} ${injBadge(p)}<span class="dm-muted"> ${esc(p.team)}</span></th>
      <td class="num">${money(p.salary)}</td><td class="num">${num(p.final)}</td>${withReason ? "" : `<td class="num">${num(p.ceiling)}</td>`}<td class="num">${popBadge(p)}</td>
      ${withReason ? `<td class="dm-reason">${esc(p.reason)}</td>` : ""}</tr>`).join("");
    return `<div class="dm-table-wrap"><table class="dm-table dm-lineup-table"><thead><tr><th scope="col">Pos</th><th scope="col">Player</th><th scope="col">Salary</th><th scope="col">Proj</th>${withReason ? "" : '<th scope="col">Ceil</th>'}<th scope="col">Own</th>${withReason ? '<th scope="col">Reason</th>' : ""}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }
  function ownTotal(lu) {
    return lu.eval.ownership_total != null ? `${num(lu.eval.ownership_total, 1)}%` : `${lu.eval.chalk_count} est. chalk`;
  }
  function totals(lu) {
    const s = lu.eval.salary;
    return `<div class="dm-li-nums dm-totals"><span>Salary ${money(s.total)}</span><span>Left ${money(s.remaining)}</span><span>Proj <b>${num(lu.final)}</b></span>
      <span>Floor ${num(lu.floor)}</span><span>Ceil ${num(lu.ceiling)}</span><span title="Total projected ownership (or estimated chalk count)">Own ${esc(ownTotal(lu))}</span>
      <span class="dm-q" title="Lineup quality score (Step 17), 0-100 within ${lu.type === "cash" ? "cash" : "tournament"} lineups">Quality ${num(lu.eval.quality, 0)}</span></div>`;
  }
  function checklist(lu) {
    return `<ul class="dm-check">${lu.eval.checklist.map((c) => `<li class="${c.ok ? "ok" : "no"}"><span aria-hidden="true">${c.ok ? "✓" : "✗"}</span><span class="visually-hidden">${c.ok ? "Pass" : "Fail"}:</span> ${esc(c.item)}</li>`).join("")}</ul>`;
  }
  function dims(lu) {
    return `<div class="dm-dims">${Object.entries(lu.eval.dimensions || {}).map(([k, v]) => `<div class="dm-dim"><span class="dm-muted">${esc(k.replace("_", " "))}</span>
      <span class="dm-bar" role="img" aria-label="${esc(k)} ${v} of 100"><span style="width:${Math.max(2, v)}%"></span></span><span>${num(v, 0)}</span></div>`).join("")}</div>`;
  }
  function salaryAlloc(lu) {
    const b = lu.eval.salary.by_position;
    return `<div class="dm-chips">${["QB", "RB", "WR", "TE", "DST"].filter((p) => b[p]).map((p) => `<span class="dm-chip-static"><span class="dm-muted">${p}</span> ${money(b[p].total)} (${pct(b[p].share)}, avg ${money(b[p].avg)})</span>`).join("")}</div>`;
  }
  const AUDIT = [["qb_stack", "QB stack"], ["double_stack", "Double stack"], ["game_stack", "Game stack"], ["bring_back", "Bring-back"],
    ["rb_construction", "RB construction"], ["wr_construction", "WR construction"], ["te_strategy", "TE strategy"], ["flex_strategy", "FLEX strategy"],
    ["leverage", "Leverage"], ["projected_ownership", "Projected ownership"], ["salary_remaining", "Salary remaining"],
    ["primary_game_script", "Primary game script"], ["biggest_failure_point", "Biggest failure point"]];
  function audit(lu) {
    return `<dl class="dm-audit">${AUDIT.map(([k, label]) => `<dt>${label}</dt><dd>${esc(lu.eval.audit[k])}</dd>`).join("")}</dl>`;
  }
  function copyBtn(lu) {
    return `<button type="button" class="dm-btn dm-btn-quiet dm-copy" data-copy="${esc(lu.players.map((p) => `${p.slot} ${p.name}`).join("\n"))}">Copy</button>`;
  }
  function lineupMini(lu) {
    return `${totals(lu)}<ol class="dm-mini">${lu.players.map((p) => `<li><span class="tp-pos">${esc(p.slot)}</span> ${esc(p.name)} <span class="dm-muted">${money(p.salary)}</span></li>`).join("")}</ol>`;
  }

  function renderCash(d) {
    const [rec, ...alts] = d.lineups.cash;
    if (!rec) return '<p class="dm-muted">Could not build a cash lineup from the current pool.</p>';
    const P = d.strategy.pools;
    return card(`${esc(rec.label)}`, note(rec.idea) + lineupTable(rec, true) + totals(rec)
        + `<div class="dm-two"><div><h4>Key strengths</h4>${bullets((rec.strengths || []).map(esc))}</div><div><h4>Main risks</h4>${bullets((rec.risks || []).map(esc))}</div></div>`
        + `<h4>Cash checklist</h4>${checklist(rec)}<h4>Quality (floor, projection, opportunity, value, stability)</h4>${dims(rec)}<h4>Salary allocation</h4>${salaryAlloc(rec)}${copyBtn(rec)}`, "dm-wide")
      + `<div class="dm-grid">${alts.map((lu) => card(esc(lu.label), lineupTable(lu, false) + totals(lu) + `<details><summary>Checklist</summary>${checklist(lu)}</details>` + copyBtn(lu))).join("")}</div>`
      + `<h3 class="dm-section">Cash player pool</h3><div class="dm-grid">
        ${poolList("QB", P.QB.cash)}${poolList("RB", P.RB.cash)}${poolList("WR", P.WR.cash)}
        ${playerList("TE (elite or cheap real role)", P.TE.pay_up.concat(P.TE.punt).filter((c) => c.injury !== "Q"))}${poolList("DST", P.DST.slice(0, 3))}</div>`;
  }

  function gppCard(lu) {
    const c = lu.eval.correlation;
    return `<article class="dm-card dm-lineup-full">
      <header class="dm-lu-head"><h3>${esc(lu.label)}: ${esc(lu.construction)}</h3></header>
      ${note(lu.idea)}${lu.eval.note ? `<p class="dm-note dm-warn">${esc(lu.eval.note)}</p>` : ""}
      ${lineupTable(lu, false)}${totals(lu)}
      <dl class="dm-audit dm-audit-short">
        <dt>Primary stack</dt><dd>${esc(lu.eval.audit.qb_stack)}</dd>
        <dt>Double stack</dt><dd>${esc(lu.eval.audit.double_stack)}</dd>
        <dt>Bring-back</dt><dd>${esc(lu.eval.audit.bring_back)}</dd>
        <dt>Leverage strategy</dt><dd>${esc(lu.eval.audit.leverage)}</dd>
        <dt>Game script</dt><dd>${esc(lu.eval.audit.primary_game_script)}</dd>
        <dt>If this lineup wins</dt><dd>${esc(lu.eval.win_scenario)}</dd>
      </dl>
      <details><summary>Correlation, checklist, quality, audit</summary>
        <h4>Correlation (score ${num(c.score)})</h4>${bullets(c.positive.map(esc).concat(c.negative.map((n) => `<span class="dm-neg">Negative: ${esc(n)}</span>`)))}
        ${c.unrelated.length ? note("Outside the stacked games: " + c.unrelated.join(", ")) : ""}
        <h4>GPP checklist</h4>${checklist(lu)}
        <h4>Quality (ceiling, correlation, leverage, environment, ownership...)</h4>${dims(lu)}
        <h4>Salary allocation</h4>${salaryAlloc(lu)}
        <h4>Roster construction audit</h4>${audit(lu)}
      </details>
      ${copyBtn(lu)}
    </article>`;
  }

  function renderGpp(d) {
    const L = d.lineups;
    return constructionList(L.constructions)
      + (L.notes.length ? note(L.notes.join(" · ")) : "")
      + `<h3 class="dm-section">GPP lineups (${L.gpp.length})</h3>`
      + note("Each is a genuinely different construction: at least 3 players different from every other GPP lineup, no player in more than 6 of 10, $49,000+ spent, never two RBs from one team or a DST facing your own players.")
      + `<div class="dm-lineups">${L.gpp.map(gppCard).join("")}</div>`
      + `<h3 class="dm-section">Contrarian GPP lineups (${L.contrarian.length})</h3>`
      + note("Ceiling discounted by Bayesian posterior ownership; a different QB stack each, outside the two most popular games, with at least two meaningful leverage plays.")
      + `<div class="dm-lineups">${L.contrarian.map(gppCard).join("")}</div>`;
  }

  // --------------------------------------------------------------- Fades
  function renderFades(d) {
    const F = d.strategy.fades;
    return `<div class="dm-grid">
      ${playerList("Cash fades", F.cash, { empty: "None flagged." })}
      ${playerList("GPP fades", F.gpp, { empty: "None flagged." })}
      ${playerList("Over-owned (overpriced chalk)", F.over_owned, { empty: "No overpriced chalk this week." })}
      ${playerList("Fragile chalk", F.fragile_chalk, { empty: "No fragile chalk this week." })}
      ${playerList("Poor roster-construction fit", F.poor_fit, { empty: "None flagged." })}
    </div>`;
  }

  // ---------------------------------------------------- Projections table
  const TABLE_COLS = [["name", "Player"], ["position", "Pos"], ["salary", "Salary"], ["consensus", "Consensus"], ["final", "Final"],
    ["floor", "Floor"], ["median", "Median"], ["ceiling", "Ceiling"], ["value", "Value"], ["ownership", "Own"], ["uncertainty", "Uncertainty"]];
  function sourceTip(p, d) {
    const labels = Object.fromEntries(d.sources.map((s) => [s.key, s.label]));
    const parts = Object.entries(p.by_source || {}).map(([k, v]) => `${labels[k] || k}: ${v == null ? "missing" : v.toFixed(1)}`);
    if (p.n_sources >= 2) parts.push(`median ${num(p.median_src)}, range ${num(p.low)}-${num(p.high)}, SD ${num(p.sd)}`);
    return parts.join("\n");
  }
  function renderTable(d) {
    const q = state.tableQuery.toLowerCase();
    let rows = d.table.filter((p) => (state.tablePos === "ALL" || p.position === state.tablePos) && (!q || p.name.toLowerCase().includes(q) || p.team.toLowerCase() === q));
    const { key, dir } = state.tableSort;
    rows = rows.slice().sort((a, b) => {
      const x = a[key], y = b[key];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return typeof x === "string" ? dir * x.localeCompare(y) : dir * (x - y);
    });
    const head = TABLE_COLS.map(([k, label]) => `<th scope="col" aria-sort="${key === k ? (dir === -1 ? "descending" : "ascending") : "none"}"><button type="button" class="dm-sort" data-sort="${k}">${label}${key === k ? (dir === -1 ? " ▼" : " ▲") : ""}</button></th>`).join("");
    const body = rows.map((p) => {
      const adj = (p.adjustments || []).map((a) => `${a.kind === "model" ? "Model" : "Sourced"}: ${a.text}`).join("\n") || "No adjustments: Final = consensus";
      return `<tr class="${p.final === 0 ? "dm-row-out" : ""}">
        <th scope="row">${esc(p.name)} ${injBadge(p)}<div class="dm-muted">${esc(p.team)} v ${esc(p.opponent)}</div></th>
        <td>${esc(p.position)}</td><td class="num">${money(p.salary)}</td>
        <td class="num" title="${esc(sourceTip(p, d))}">${num(p.consensus)} <span class="dm-muted">(${p.n_sources})</span></td>
        <td class="num" title="${esc(adj)}"><b>${num(p.final)}</b>${(p.adjustments || []).some((a) => a.kind === "model") ? '<span class="dm-adj" aria-label="model-adjusted">*</span>' : ""}</td>
        <td class="num">${num(p.floor)}</td><td class="num">${num(p.median)}</td>
        <td class="num" title="${p.app_ceiling != null ? "Blend of the calibrated 85th percentile and the matchup Ceiling (" + num(p.app_ceiling) + ")" : "Calibrated 85th percentile"}">${num(p.ceiling)}</td>
        <td class="num">${num(p.value, 2)}</td><td class="num">${popBadge(p)}</td><td>${uncBadge(p)}</td></tr>`;
    }).join("");
    const posBtns = ["ALL", "QB", "RB", "WR", "TE", "DST"].map((pos) => `<button type="button" class="dm-chip" data-pos="${pos}" aria-pressed="${state.tablePos === pos}">${pos}</button>`).join("");
    return card("Player projection table", note("Consensus = equal-weight mean of the sources that project the player (count in parentheses; hover for each source, or \"missing\"). Final = consensus + labeled adjustments (* = model matchup adjustment; hover for details). Floor / Median = 15th / 50th percentile of past actual-vs-consensus outcomes at the position and projection range.")
      + `<div class="dm-table-tools">${posBtns}<input type="search" id="dm-search" placeholder="Search player or team" value="${esc(state.tableQuery)}" aria-label="Search player or team" /></div>
      <div class="dm-table-wrap dm-table-tall"><table class="dm-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`
      + note(`${rows.length} players.` + (d.no_source_players.length ? " Playable with no source projection (left blank, not estimated): " + d.no_source_players.join(", ") : "")), "dm-wide");
  }

  // ------------------------------------------------------------- Method
  function renderMethod(d) {
    const src = d.sources.map((s) => `<tr><th scope="row">${esc(s.label)}</th><td class="num">${s.available ? s.matched_on_slate : "-"}</td><td>${s.available ? esc(s.fetched_at || "") : "unavailable this week"}</td></tr>`).join("");
    const un = d.unavailable_sources.map((u) => `<b>${esc(u.label)}</b>: ${esc(u.reason)}`);
    const acc = d.accuracy || {};
    const rel = acc.relative_mae || {};
    const labels = Object.fromEntries(d.sources.map((s) => [s.key, s.label]));
    const accRows = Object.entries(rel).map(([pos, bySrc]) => `<tr><th scope="row">${esc(pos)}</th>${Object.keys(labels).map((k) => {
      const v = bySrc[k];
      return `<td class="num" title="${v ? `MAE ${v.mae} vs Sleeper ${v.sleeper_mae} on the same ${v.games} player-games` : "No graded history (CBS serves only the current week)"}">${v ? v.ratio.toFixed(3) : "-"}</td>`;
    }).join("")}<td class="num">${acc.consensus && acc.consensus[pos] ? `${acc.consensus[pos].mae_consensus} vs ${acc.consensus[pos].mae_sleeper}` : "-"}</td><td>${esc((d.weighting || {})[pos] || "")}</td></tr>`).join("");
    const missing = d.strategy.missing_data.map((m) => `<b>${esc(m.item)}</b>: ${esc(m.why)}`);
    const tr = d.trenches;
    const trenchCard = tr ? card("Line play &amp; scheme data", note(`${esc(tr.window)}. Used in the QB, RB, WR and DST pools (scores and reasons), chalk failure modes and game notes; projections themselves are not changed.`)
      + bullets(tr.sources.map(esc)) + note(tr.note)
      + `<ul class="dm-bullets">${tr.references.map((r) => `<li><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.label)}</a></li>`).join("")}</ul>`) : "";
    return `<div class="dm-grid">
      ${card("Missing data (not guessed)", bullets(missing) + note("Used instead where possible: projected carries/targets/TDs from the sources' stat lines, and nflverse target share, air-yards share, aDOT, carries and carry share."))}
      ${trenchCard}
      ${card("Sources this week", `<table class="dm-table"><thead><tr><th scope="col">Source</th><th scope="col">Players matched</th><th scope="col">Fetched (UTC)</th></tr></thead><tbody>${src}</tbody></table>`
        + note("FantasyPros' public page lists only the top 10 per position (the rest needs a premium account). FFToday has no DST lines or fumbles. Sources refresh every 2 hours; DraftKings salaries and injury statuses every 5 minutes.") + "<h4>Not used</h4>" + bullets(un))}
      ${card("Historical accuracy &amp; weighting", note(`Each source's mean absolute error (actual DK points) divided by Sleeper's on the same player-games, ${(acc.weeks || []).length} weeks graded. Below 1.000 = more accurate. Weights become 1/MAE only if sources differ by more than 5%.`)
        + `<div class="dm-table-wrap"><table class="dm-table"><thead><tr><th scope="col">Pos</th>${Object.values(labels).map((l) => `<th scope="col">${esc(l)}</th>`).join("")}<th scope="col">MAE consensus vs Sleeper</th><th scope="col">Weighting</th></tr></thead><tbody>${accRows}</tbody></table></div>`, "dm-wide")}
      ${card("How lineups are built", bullets([
        "<b>Cash</b>: maximize floor + projection + projected opportunities, minus a penalty for high uncertainty. No Questionable players, no cheap RB/WR/TE without a real projected role, TE must be elite or a cheap real role, never two RBs from one team, $48,500+ spent. 1 recommended + 4 alternates (2+ players different).",
        "<b>GPP</b>: maximize ceiling, nudged by game environment, +1.5 for a meaningful leverage play, -2 for fragile/overpriced chalk, +0.5 for WRs (FLEX lean). Every player needs a ceiling path and cheap players need a real role. Each construction tries a QB double stack + bring-back first. No DST vs your own players, never two RBs from one team, $49,000+ spent, 3+ players different from every other GPP lineup, max 6 of 10 for any player.",
        "<b>Constructions</b>: primary game stack (best environment, WR bring-back), contrarian game stack (good environment the field is ignoring), chalk + leverage, expensive QB with RB/TE savings, mid-tier RB leverage, elite TE, low-owned ceiling, naked rushing QB (only when his rushing is 25%+ of his projection), second environment with a WR2 bring-back, 4-WR onslaught.",
        "<b>Meaningful leverage</b>: lower-owned (Bayesian posterior 8% or less) AND a top-quarter ceiling at the position AND a real role AND not Questionable.",
        "<b>Chalk classes</b>: necessary/value (cheap, top-3 value), fragile (Questionable or 2+ failure modes), overpriced (value below the position median), cash-not-GPP (safe floor, limited ceiling), leverage-stack usable (popular player in an under-owned game), strong.",
        "<b>Quality score</b> (0-100 within cash or tournament lineups): GPP weights ceiling 25%, correlation 20%, leverage 15%, environment 15%, ownership 10%, projection/salary/uniqueness 5% each; Cash weights floor 30%, projection 25%, opportunity 20%, stability 15%, value 10%.",
        "Questionable players count 90% in every lineup objective; their projection doesn't change.",
      ]), "dm-wide")}
      ${card("How projections are built", bullets([
        "<b>Consensus</b>: every source's projected stat line scored with DraftKings rules, then mean, median, range, SD and source count. Missing sources stay missing.",
        "<b>Final</b> = consensus, then only DraftKings injury status (sourced) and the backtested matchup nudge (model, +/-5% max).",
        "<b>Floor / Median</b>: 15th / 50th percentile of actual / consensus in past weeks, by position and projection range. <b>Ceiling</b>: average of that 85th percentile and the matchup Ceiling.",
        `<b>Ownership</b>: ${esc(d.ownership.note)}`,
      ]), "dm-wide")}
    </div>`;
  }

  // ------------------------------------------------------------- plumbing
  function ctx() {
    return { esc, num, money, card, note, bullets, injBadge, popBadge, state, rerender: render,
             reload: (opts) => { if (opts.contest) state.contest = opts.contest; if ("contestSize" in opts) state.contestSize = opts.contestSize; load(false); } };
  }
  const renderOwnership = (d) => window.DFSOwnership.render(d, ctx());

  const VIEWS = { summary: renderSummary, slate: renderSlate, pools: renderPools, ownership: renderOwnership, chalk: renderChalk, stacks: renderStacks,
                  cash: renderCash, gpp: renderGpp, fades: renderFades, table: renderTable, method: renderMethod };

  function render() {
    const d = state.data;
    if (!d) return;
    if (!d.available) { panelEl.innerHTML = `<p class="dm-muted">${esc(d.reason)}</p>`; return; }
    const label = (tabs.find((t) => t.dataset.tab === state.tab) || tabs[0]).textContent;
    panelEl.innerHTML = `<h2 class="visually-hidden">${esc(label)}</h2>` + (VIEWS[state.tab] || renderSummary)(d);
  }

  function selectTab(name, focus) {
    state.tab = VIEWS[name] ? name : "summary";
    try { localStorage.setItem(TAB_KEY, state.tab); } catch (e) { /* private mode */ }
    for (const t of tabs) {
      const on = t.dataset.tab === state.tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      if (on && focus) { t.focus(); t.scrollIntoView({ block: "nearest", inline: "nearest" }); }
    }
    render();
  }

  async function load(force) {
    state.season = DFS.season;
    state.week = DFS.week;
    weekEl.textContent = `-- Week ${state.week}`;
    asofEl.textContent = "Building model...";
    if (force || !state.data) panelEl.innerHTML = '<p class="dm-muted loading">Pulling every source and building lineups (can take ~10s on a cold start)...</p>';
    panelEl.setAttribute("aria-busy", "true");
    const params = new URLSearchParams({ season: state.season, week: state.week });
    if (state.slate) params.set("slate_id", state.slate);
    params.set("contest", state.contest);
    if (state.contestSize) params.set("contest_size", state.contestSize);
    try {
      const body = await DFS.getJson(`/api/dfs-model?${params}`, "model");
      state.data = body;
      if (body.available) {
        state.slate = body.slate.slate_id;
        slateEl.innerHTML = body.slates.map((s) => `<option value="${esc(s.slate_id)}"${s.slate_id === body.slate.slate_id ? " selected" : ""}>${esc(s.label)}</option>`).join("");
        const when = new Date(body.generated_at);
        asofEl.textContent = `Built ${when.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })} from ${body.sources.filter((s) => s.available).length} sources`;
      } else {
        slateEl.innerHTML = "";
        asofEl.textContent = "";
      }
      panelEl.removeAttribute("aria-busy");
      selectTab(state.tab);
    } catch (err) {
      if (DFS.isAbort(err)) return;
      panelEl.removeAttribute("aria-busy");
      asofEl.textContent = "";
      panelEl.innerHTML = `<p class="dm-error">Could not build the DFS model: ${esc(err.message)}</p>`;
    }
  }

  for (const t of tabs) t.addEventListener("click", () => { selectTab(t.dataset.tab); t.scrollIntoView({ block: "nearest", inline: "nearest" }); });
  document.querySelector(".dm-tabs").addEventListener("keydown", (e) => {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const i = tabs.findIndex((t) => t.dataset.tab === state.tab);
    const next = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : (i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
    selectTab(tabs[next].dataset.tab, true);
  });
  slateEl.addEventListener("change", () => { state.slate = slateEl.value; load(true); });
  document.getElementById("dm-refresh").addEventListener("click", () => load(true));
  DFS.onWeekChange(() => { state.slate = null; state.data = null; load(true); });
  panelEl.addEventListener("submit", (e) => { if (state.tab === "ownership") window.DFSOwnership.submit(e, ctx()); });

  panelEl.addEventListener("click", (e) => {
    if (state.tab === "ownership" && window.DFSOwnership.click(e, ctx())) return;
    const go = e.target.closest("[data-goto]");
    if (go) {
      if (go.dataset.pos) state.poolPos = go.dataset.pos;
      selectTab(go.dataset.goto);
      window.scrollTo({ top: document.getElementById("dfs-model").offsetTop, behavior: "smooth" });
      return;
    }
    const sortBtn = e.target.closest("[data-sort]");
    if (sortBtn) {
      const k = sortBtn.dataset.sort;
      state.tableSort = { key: k, dir: state.tableSort.key === k ? -state.tableSort.dir : (k === "name" || k === "position" ? 1 : -1) };
      render();
      return;
    }
    const chip = e.target.closest("[data-pos]");
    if (chip) { state.tablePos = chip.dataset.pos; render(); return; }
    const pchip = e.target.closest("[data-poolpos]");
    if (pchip) { state.poolPos = pchip.dataset.poolpos; render(); return; }
    const copy = e.target.closest("[data-copy]");
    if (copy && navigator.clipboard) {
      navigator.clipboard.writeText(copy.dataset.copy).then(() => {
        copy.textContent = "Copied";
        setTimeout(() => { copy.textContent = "Copy"; }, 1500);
      }).catch(() => {});
    }
  });
  let searchTimer = null;
  panelEl.addEventListener("input", (e) => {
    if (state.tab === "ownership" && window.DFSOwnership.input(e, ctx())) return;
    if (e.target.id !== "dm-search") return;
    state.tableQuery = e.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      const cur = document.getElementById("dm-search");
      const pos = cur ? cur.selectionStart : state.tableQuery.length;
      render();
      const again = document.getElementById("dm-search");
      if (again) { again.focus(); again.setSelectionRange(pos, pos); }
    }, 120);
  });

  load(true);
})();
