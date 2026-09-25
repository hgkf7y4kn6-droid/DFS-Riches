/* Ownership tab of the DFS Model page: the Bayesian ownership report (sections A-M)
   plus the forms that feed it (sources, crowd submissions, actual contest ownership).
   Exposes window.DFSOwnership = { render(d, ctx), click(e, ctx), submit(e, ctx) }. */
(function () {
  "use strict";

  const SUBVIEWS = [["table", "Ownership table"], ["ranks", "Rank odds"], ["movement", "Movement & history"],
    ["sources", "Sources"], ["crowd", "Crowd"], ["concentration", "Concentration"], ["dup", "Duplication & leverage"],
    ["news", "News & confidence"], ["add", "Add data"]];
  const LABEL_TIPS = {
    "ACTUAL": "Actual contest ownership (uploaded DraftKings contest results)",
    "PROJECTED": "A projection reported by a named ownership source",
    "CROWDSOURCED": "Crowdsourced submissions, reliability-weighted",
    "BAYESIAN POSTERIOR": "The model's posterior: behavioral prior + sources + crowd + news",
    "SIMULATED": "From Monte Carlo simulation (posterior draws or simulated field lineups)",
  };
  const view = { sub: "table", pos: "ALL", q: "", sort: { key: "mean", dir: -1 }, open: null };
  let searchTimer = null;

  const tag = (label) => `<span class="own-label" title="${LABEL_TIPS[label]}">${label}</span>`;
  const pct = (v, d) => (v == null ? "-" : Number(v).toFixed(d == null ? 1 : d) + "%");
  const prob = (v) => (v == null ? "-" : Math.round(v * 100) + "%");
  const ci = (a) => (a ? `${Number(a[0]).toFixed(1)}-${Number(a[1]).toFixed(1)}` : "-");

  function confBadge(c) {
    const cls = { "VERY HIGH": "vh", "HIGH": "h", "MEDIUM": "m", "LOW": "l", "VERY LOW": "vl" }[c] || "vl";
    return `<span class="own-conf own-conf-${cls}">${c}</span>`;
  }

  // Interval strip: 95% hairline, 80% band, 50% band, mean dot. Single hue; scale 0..max.
  function strip(r, max) {
    const x = (v) => Math.max(0, Math.min(100, (v / max) * 100));
    const tip = `${r.name}: mean ${pct(r.mean)}, 50% ${ci(r.ci50)}, 80% ${ci(r.ci80)}, 95% ${ci(r.ci95)}`;
    return `<svg class="own-strip" viewBox="0 0 100 12" preserveAspectRatio="none" role="img" aria-label="${tip}"><title>${tip}</title>
      <line x1="${x(r.ci95[0])}" x2="${x(r.ci95[1])}" y1="6" y2="6" class="s95"/>
      <rect x="${x(r.ci80[0])}" width="${Math.max(0.5, x(r.ci80[1]) - x(r.ci80[0]))}" y="3.5" height="5" rx="1" class="s80"/>
      <rect x="${x(r.ci50[0])}" width="${Math.max(0.5, x(r.ci50[1]) - x(r.ci50[0]))}" y="2" height="8" rx="1" class="s50"/>
      <circle cx="${x(r.mean)}" cy="6" r="2.2" class="sdot"/></svg>`;
  }

  function meter(p) {
    return `<span class="own-meter" title="${prob(p)}"><span style="width:${Math.max(1, p * 100)}%"></span></span>`;
  }

  function banner(d, ctx) {
    const o = d.ownership_model, ms = o.model_state;
    const onlyPrior = o.table.every((r) => !r.n_sources && !r.crowd_users && r.actual == null);
    const contests = Object.entries(o.contests).filter(([k]) => !k.startsWith("showdown"));
    return `<div class="own-bar">
      <label>Contest <select id="own-contest">${contests.map(([k, v]) => `<option value="${k}"${k === o.contest ? " selected" : ""}>${ctx.esc(v)}</option>`).join("")}</select></label>
      <label>Contest size <input id="own-size" type="number" min="2" max="2000000" value="${o.contest_size}" /></label>
      <button type="button" class="dm-btn" data-own-apply="1">Apply</button>
      <span class="dm-muted">Lock ${o.lock ? new Date(o.lock).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }) : "-"}
        (${o.hours_to_lock > 0 ? o.hours_to_lock.toFixed(1) + "h away" : "locked"})${o.history_written ? " · snapshot saved: " + ctx.esc(o.history_written) : ""}</span>
    </div>
    ${onlyPrior ? `<p class="own-warn">No ownership sources, crowd submissions or actual results for this slate yet, so every number below is the
      behavioral prior alone (salary, value, projection, Vegas) with VERY LOW confidence and wide intervals. Add data in
      <button type="button" class="dm-link" data-own-sub="add">Add data</button> and it updates by Bayes' rule.</p>` : ""}
    <p class="dm-note">Labels: ${Object.keys(LABEL_TIPS).map(tag).join(" ")} Nothing projected is ever shown as actual.</p>`;
  }

  function subnav() {
    return `<div class="dm-table-tools own-subnav">${SUBVIEWS.map(([k, label]) => `<button type="button" class="dm-chip" data-own-sub="${k}" aria-pressed="${view.sub === k}">${label}</button>`).join("")}</div>`;
  }

  // ------------------------------------------------------------- A/B/I/K
  const COLS = [["name", "Player"], ["position", "Pos"], ["salary", "Salary"], ["mean", "Bayesian own"], ["median", "Median"],
    ["ci50", "50% CI"], ["ci80", "80% CI"], ["ci95", "95% CI"], ["strip", "Interval"], ["cash", "Cash"], ["gpp", "GPP"],
    ["showdown", "Showdown"], ["crowd", "Crowd"], ["trend", "Trend"], ["confidence", "Confidence"]];

  function detail(r, ctx) {
    const parts = (r.source_parts || []).map((p) => `<li>${tag("PROJECTED")} ${ctx.esc(p.source)} (${ctx.esc(p.contest)}): reported ${pct(p.reported)},
      bias-adjusted ${pct(p.bias_adjusted)}, on this contest's scale ${pct(p.estimate)} · weight ${p.weight} · N ${p.n} · ${p.age_h}h old${p.scored ? "" : " · unscored source (default error)"}</li>`).join("");
    return `<div class="own-detail">
      <div class="own-models">
        <div><b>Model C</b> behavioral prior ${pct(r.model_c)} <span class="dm-muted">(N ${r.n_c})</span></div>
        <div><b>Model A</b> sources ${r.sources_mean != null ? pct(r.sources_mean) : "-"} <span class="dm-muted">(${r.n_sources} source${r.n_sources === 1 ? "" : "s"}, effective N ${r.n_a}${r.dispersion != null && r.n_sources > 1 ? `, dispersion ${pct(r.dispersion)}` : ""})</span></div>
        <div><b>Model B</b> crowd ${r.crowd != null ? pct(r.crowd) : "-"} <span class="dm-muted">(${r.crowd_users} contributor${r.crowd_users === 1 ? "" : "s"}, effective N ${r.n_b})</span></div>
        <div><b>Posterior</b> ${tag("BAYESIAN POSTERIOR")} ${pct(r.mean)} <span class="dm-muted">(total N ${r.n_total}${r.calibrated ? ", calibrated" : ""})</span></div>
        ${r.actual != null ? `<div><b>Actual</b> ${tag("ACTUAL")} ${pct(r.actual)}</div>` : ""}
      </div>
      ${parts ? `<ul class="dm-bullets">${parts}</ul>` : ""}
      <div class="dm-chips">${tag("SIMULATED")} ${Object.entries(r.p_over).map(([t, p]) => `<span class="dm-chip-static">P(&gt;${t}%) ${prob(p)}</span>`).join("")}
        <span class="dm-chip-static">mode ${pct(r.mode)}</span><span class="dm-chip-static">SD ${pct(r.sd)}</span>
        <span class="dm-chip-static">P(top 5 owned) ${prob(r.p_top5)}</span><span class="dm-chip-static">P(top 10) ${prob(r.p_top10)}</span>
        <span class="dm-chip-static">expected rank ${r.rank_mean != null ? r.rank_mean : "outside top 10"}</span></div>
      <p class="dm-note">Confidence ${r.confidence}: ${ctx.esc((r.confidence_why || []).join("; "))}${r.news ? " · " + ctx.esc(r.news) : ""}</p>
      ${r.spike && r.spike.flag ? `<p class="own-warn">${ctx.esc(r.spike.flag)} (P up ${prob(r.spike.p_up)}, P down ${prob(r.spike.p_down)})</p>` : ""}
    </div>`;
  }

  function renderTable(d, ctx) {
    const o = d.ownership_model;
    const q = view.q.toLowerCase();
    let rows = o.table.filter((r) => (view.pos === "ALL" || r.position === view.pos) && (!q || r.name.toLowerCase().includes(q) || r.team.toLowerCase() === q));
    const val = (r, k) => (k === "cash" || k === "gpp" ? r.contests[k] : k === "ci50" || k === "ci80" || k === "ci95" ? r[k][1] - r[k][0]
      : k === "showdown" ? (r.showdown ? r.showdown.flex : null) : k === "strip" ? r.mean : r[k]);
    const { key, dir } = view.sort;
    rows = rows.slice().sort((a, b) => {
      const x = val(a, key), y = val(b, key);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return typeof x === "string" ? dir * x.localeCompare(y) : dir * (x - y);
    });
    const max = Math.max(10, ...rows.map((r) => r.ci95[1]));
    const head = COLS.map(([k, label]) => `<th scope="col" aria-sort="${key === k ? (dir === -1 ? "descending" : "ascending") : "none"}"><button type="button" class="dm-sort" data-own-sort="${k}">${label}${key === k ? (dir === -1 ? " ▼" : " ▲") : ""}</button></th>`).join("");
    const body = rows.map((r) => `<tr class="${r.news && r.news.startsWith("Confirmed") ? "dm-row-out" : ""}">
        <th scope="row"><button type="button" class="own-open" data-own-open="${ctx.esc(r.key)}" aria-expanded="${view.open === r.key}">${ctx.esc(r.name)}</button> ${ctx.injBadge(r)}<div class="dm-muted">${ctx.esc(r.team)} v ${ctx.esc(r.opponent)}</div></th>
        <td>${ctx.esc(r.position)}</td><td class="num">${ctx.money(r.salary)}</td>
        <td class="num"><b>${pct(r.mean)}</b>${r.actual != null ? `<div class="dm-muted">actual ${pct(r.actual)}</div>` : ""}</td>
        <td class="num">${pct(r.median)}</td><td class="num">${ci(r.ci50)}</td><td class="num">${ci(r.ci80)}</td><td class="num">${ci(r.ci95)}</td>
        <td class="own-strip-cell">${strip(r, max)}</td>
        <td class="num">${pct(r.contests.cash)}</td><td class="num">${pct(r.contests.gpp)}</td>
        <td class="num">${r.showdown ? `<span title="${ctx.esc(r.showdown.slate)}">FLEX ${pct(r.showdown.flex)}<br>CPT ${pct(r.showdown.cpt)}</span>` : '<span class="dm-muted" title="No Showdown slate for this game">-</span>'}</td>
        <td class="num">${r.crowd != null ? pct(r.crowd) : "-"}</td>
        <td class="num">${r.trend != null ? (r.trend > 0 ? "+" : "") + r.trend.toFixed(1) : "-"}${r.spike && r.spike.flag ? ' <span class="own-spike" title="' + ctx.esc(r.spike.flag) + '">!</span>' : ""}</td>
        <td>${confBadge(r.confidence)}</td></tr>
        ${view.open === r.key ? `<tr class="own-detail-row"><td colspan="${COLS.length}">${detail(r, ctx)}</td></tr>` : ""}`).join("");
    const posBtns = ["ALL", "QB", "RB", "WR", "TE", "DST"].map((p) => `<button type="button" class="dm-chip" data-own-pos="${p}" aria-pressed="${view.pos === p}">${p}</button>`).join("");
    return ctx.card(`A-B. Bayesian ownership table ${tag("BAYESIAN POSTERIOR")}`,
      ctx.note(`${o.contest_label} posterior mean, median and credible intervals from 10,000 simulations per player; Cash and GPP columns are each contest's own posterior; Showdown is the player's FLEX / CPT posterior when his game has a Showdown slate. Click a player for the model breakdown (behavioral prior, sources, crowd), threshold probabilities and rank odds. ${o.table_omitted} players under 0.3% not shown.`)
      + `<div class="dm-table-tools">${posBtns}<input type="search" id="own-search" placeholder="Search player or team" value="${ctx.esc(view.q)}" aria-label="Search player or team" /></div>
      <div class="dm-table-wrap dm-table-tall"><table class="dm-table own-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`, "dm-wide");
  }

  // ------------------------------------------------------------------ L
  function renderRanks(d, ctx) {
    const o = d.ownership_model;
    const rows = o.table.slice(0, 20).map((r) => `<tr><th scope="row">${ctx.esc(r.name)} <span class="dm-muted">${ctx.esc(r.position)}</span></th>
      <td class="num">${pct(r.mean)}</td>
      ${["1", "2-3", "4-5", "6-10", "11+"].map((k) => `<td class="num">${meter(r.rank_probs[k])} ${prob(r.rank_probs[k])}</td>`).join("")}
      <td class="num">${prob(r.p_top5)}</td><td class="num">${prob(r.p_top10)}</td><td class="num">${r.rank_mean}</td></tr>`).join("");
    return ctx.card(`L. Ownership rank distribution ${tag("SIMULATED")}`,
      ctx.note("How often each player finishes at each ownership rank across 10,000 posterior draws -- the uncertainty a single number hides.")
      + `<div class="dm-table-wrap"><table class="dm-table own-num-heads"><thead><tr><th scope="col">Player</th><th scope="col">Mean</th><th scope="col">P(#1)</th><th scope="col">P(#2-3)</th><th scope="col">P(#4-5)</th><th scope="col">P(#6-10)</th><th scope="col">P(outside top 10)</th><th scope="col">P(top 5)</th><th scope="col">P(top 10)</th><th scope="col">E[rank]</th></tr></thead><tbody>${rows}</tbody></table></div>`, "dm-wide");
  }

  // --------------------------------------------------------------- C / M
  function sparkline(series) {
    const pts = series.points;
    const w = 220, h = 54, pad = 6;
    const ys = pts.map((p) => p.mean);
    const lo = Math.min(...ys), hi = Math.max(...ys);
    const span = Math.max(1, hi - lo);
    const t0 = new Date(pts[0].t).getTime(), t1 = new Date(pts[pts.length - 1].t).getTime();
    const X = (t) => pad + (t1 > t0 ? ((new Date(t).getTime() - t0) / (t1 - t0)) * (w - 2 * pad - 40) : 0);
    const Y = (v) => h - pad - ((v - lo) / span) * (h - 2 * pad);
    const path = pts.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p.mean).toFixed(1)}`).join(" ");
    const last = pts[pts.length - 1];
    const dots = pts.map((p) => `<circle cx="${X(p.t).toFixed(1)}" cy="${Y(p.mean).toFixed(1)}" r="4" class="sp-dot" tabindex="0"><title>${new Date(p.t).toLocaleString()}: ${p.mean.toFixed(1)}%</title></circle>`).join("");
    return `<figure class="own-spark"><figcaption>${series.name}</figcaption>
      <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${series.name} ownership history, ${pts.length} snapshots, now ${last.mean.toFixed(1)}%">
        <path d="${path}" class="sp-line"/>${dots}
        <text x="${X(last.t) + 8}" y="${Y(last.mean) + 4}" class="sp-label">${last.mean.toFixed(1)}%</text></svg></figure>`;
  }

  function renderMovement(d, ctx) {
    const o = d.ownership_model;
    const mv = o.movement.map((m) => `<tr><th scope="row">${ctx.esc(m.name)} <span class="dm-muted">${ctx.esc(m.position)}</span></th>
      <td class="num">${pct(m.opening)}</td><td class="num">${pct(m.current)}</td><td class="num">${m.change > 0 ? "+" : ""}${pct(m.change)}</td>
      <td class="num">${m.change_pct == null ? "-" : (m.change_pct > 0 ? "+" : "") + m.change_pct + "%"}</td>
      <td class="num">${m.velocity_per_hour > 0 ? "+" : ""}${pct(m.velocity_per_hour, 2)}/h</td>
      <td class="num" title="P(ownership ends above ${pct(m.target)})">${prob(m.p_further_increase)}</td></tr>`).join("");
    const spikes = o.spikes.map((s) => `<li><b>${ctx.esc(s.name)}</b>: ${ctx.esc(s.flag)} -- P(up 5+ pts) ${prob(s.p_up)}, P(down 5+ pts) ${prob(s.p_down)}</li>`).join("");
    const hist = o.history.slice().reverse().map((h) => `<li>${new Date(h.timestamp).toLocaleString()}: ${ctx.esc(h.trigger)}</li>`).join("");
    const sparks = o.history_series.filter((s) => s.points.length >= 2);
    return ctx.card(`C. Ownership movement ${tag("BAYESIAN POSTERIOR")}`,
        ctx.note("Opening = the first stored snapshot for this slate. Velocity = change per hour since opening. The last column is the simulated chance ownership ends above the current level plus the trend through lock (at least +1 pt).")
        + (mv ? `<div class="dm-table-wrap"><table class="dm-table own-num-heads"><thead><tr><th scope="col">Player</th><th scope="col">Opening</th><th scope="col">Current</th><th scope="col">Change</th><th scope="col">Change %</th><th scope="col">Velocity</th><th scope="col">P(further increase)</th></tr></thead><tbody>${mv}</tbody></table></div>`
          : '<p class="dm-muted">Only one snapshot so far -- movement appears once new information arrives.</p>'), "dm-wide")
      + `<div class="dm-grid">${ctx.card(`Spike detection ${tag("SIMULATED")}`, ctx.note("P(current > previous snapshot + 5 pts); flagged above 80% and 95%.") + (spikes ? `<ul class="dm-bullets">${spikes}</ul>` : '<p class="dm-muted">No material spikes or drops vs the previous snapshot.</p>'))}
        ${ctx.card("M. Projection history", ctx.note("Every snapshot is timestamped and never overwritten; the last one before lock is what gets graded.") + `<ol class="dm-bullets own-hist">${hist}</ol>`)}</div>`
      + (sparks.length ? ctx.card(`Posterior history, most-owned players ${tag("BAYESIAN POSTERIOR")}`, `<div class="own-sparks">${sparks.map(sparkline).join("")}</div>`, "dm-wide") : "");
  }

  // ------------------------------------------------------------------ D
  function renderSources(d, ctx) {
    const o = d.ownership_model;
    const rows = o.sources.map((s) => `<tr><th scope="row">${ctx.esc(s.source)}</th><td class="num">${s.players}</td>
      <td>${s.scored ? `graded on ${s.graded_n}` : "unscored (default error assumed)"}</td><td class="num">${s.mae != null ? pct(s.mae, 2) : "-"}</td>
      <td class="num">${s.bias != null ? pct(s.bias, 2) : "-"}</td><td class="num">${s.reliability}</td><td class="num">${s.avg_effective_n}</td><td class="num">${s.avg_age_h}h</td></tr>`).join("");
    const corr = o.source_corr.map((c) => `<li>${ctx.esc(c.pair.replace("|", " / "))}: error correlation ${c.rho} (n ${c.n})</li>`).join("");
    const disagree = o.disagreement.map((r) => `<tr><th scope="row">${ctx.esc(r.name)} <span class="dm-muted">${ctx.esc(r.position)}</span></th><td class="num">${pct(r.mean)}</td>
      <td class="num">${r.dispersion != null ? pct(r.dispersion) : "-"}</td><td class="num">${r.n_sources}</td><td class="num">${r.ci80_width}</td><td class="num">${r.crowd_gap != null ? (r.crowd_gap > 0 ? "+" : "") + r.crowd_gap : "-"}</td></tr>`).join("");
    return ctx.card(`D. Source consensus ${tag("PROJECTED")}`,
        ctx.note(`Each source is bias-corrected and weighted by 1/(MAE + 1 pt) from its graded history; unscored sources are assumed to miss by ${o.defaults.source_sigma} pts. Sources whose errors move together are discounted (effective N = sum N / (1 + (k-1) rho), rho = ${o.defaults.source_rho} until measured), so five sites copying one projection don't create false certainty.`)
        + (rows ? `<div class="dm-table-wrap"><table class="dm-table own-num-heads"><thead><tr><th scope="col">Source</th><th scope="col">Players</th><th scope="col">History</th><th scope="col">MAE</th><th scope="col">Bias</th><th scope="col">Reliability</th><th scope="col">Avg effective N</th><th scope="col">Avg age</th></tr></thead><tbody>${rows}</tbody></table></div>`
          : '<p class="dm-muted">No ownership sources added for this slate. <button type="button" class="dm-link" data-own-sub="add">Add one</button></p>')
        + (corr ? `<h4>Measured error correlations</h4><ul class="dm-bullets">${corr}</ul>` : ""), "dm-wide")
      + ctx.card("F. Ownership disagreement", ctx.note("Players where sources spread by more than 5 pts (SD), or the crowd is 3+ pts from the posterior. Dispersion is disagreement between estimates; the 80% interval width is the model's own uncertainty.")
        + (disagree ? `<div class="dm-table-wrap"><table class="dm-table own-num-heads"><thead><tr><th scope="col">Player</th><th scope="col">Posterior</th><th scope="col">Source SD</th><th scope="col">Sources</th><th scope="col">80% CI width</th><th scope="col">Crowd - posterior</th></tr></thead><tbody>${disagree}</tbody></table></div>` : '<p class="dm-muted">No disagreement flags.</p>'), "dm-wide");
  }

  // ------------------------------------------------------------------ E
  function renderCrowd(d, ctx) {
    const c = d.ownership_model.crowd;
    const tiles = [["Contributors", c.contributors], ["Valid submissions", c.submissions], ["Players covered", c.players_covered],
      ["Average crowd projection", pct(c.average)], ["Median crowd projection", pct(c.median)], ["Crowd SD", pct(c.sd)],
      ["Historical crowd MAE", c.historical_mae != null ? pct(c.historical_mae, 2) : "not graded yet"], ["High-reliability contributors", c.high_reliability]]
      .map(([k, v]) => `<div class="own-tile"><div class="dm-muted">${k}</div><div class="own-tile-v">${v}</div></div>`).join("");
    const rows = c.players.map((p) => `<tr><th scope="row">${ctx.esc(p.name)} <span class="dm-muted">${ctx.esc(p.position)}</span></th><td class="num">${pct(p.crowd)}</td><td class="num">${pct(p.bayesian)}</td>
      <td class="num">${p.difference > 0 ? "+" : ""}${p.difference.toFixed(1)}</td><td class="num">${p.users}</td></tr>`).join("");
    return ctx.card(`E. Crowd dashboard ${tag("CROWDSOURCED")}`,
      ctx.note(`Each contributor is weighted by 1/(MAE + 1 pt) -- newcomers start at an assumed ${d.ownership_model.defaults.crowd_mae} pt MAE and earn weight as their past submissions are graded -- and by their stated confidence. Not one-user-one-vote. Differences are crowd/model disagreement, not a lineup recommendation.`)
      + `<div class="own-tiles">${tiles}</div>`
      + (rows ? `<div class="dm-table-wrap"><table class="dm-table own-num-heads"><thead><tr><th scope="col">Player</th><th scope="col">Crowd (weighted)</th><th scope="col">Bayesian</th><th scope="col">Difference</th><th scope="col">Contributors</th></tr></thead><tbody>${rows}</tbody></table></div>`
        : '<p class="dm-muted">No crowd submissions yet. <button type="button" class="dm-link" data-own-sub="add">Submit yours</button></p>'), "dm-wide");
  }

  // --------------------------------------------------------------- G / 22
  function barChart(items, ctx) {
    const max = Math.max(1, ...items.map((i) => i.count));
    const bw = 34, gap = 14, h = 120, top = 18;
    const w = items.length * (bw + gap);
    const bars = items.map((it, i) => {
      const bh = (it.count / max) * (h - top - 20);
      const x = i * (bw + gap) + gap / 2, y = h - 20 - bh;
      return `<g tabindex="0"><title>${it.range}: ${it.count} players</title>
        <path d="M${x},${h - 20} V${y + 4} q0,-4 4,-4 H${x + bw - 4} q4,0 4,4 V${h - 20} Z" class="own-bar-mark"/>
        <text x="${x + bw / 2}" y="${y - 4}" class="own-bar-val">${it.count}</text>
        <text x="${x + bw / 2}" y="${h - 6}" class="own-bar-lab">${it.range}</text></g>`;
    }).join("");
    return `<svg class="own-bars" viewBox="0 0 ${w} ${h}" role="img" aria-label="Players by projected ownership range">
      <line x1="0" x2="${w}" y1="${h - 20}" y2="${h - 20}" class="own-axis"/>${bars}</svg>`;
  }

  function shareTable(title, rows, ctx, limit) {
    return `<div><h4>${title}</h4><table class="dm-table own-num-heads"><tbody>${rows.slice(0, limit || 8).map((r) => `<tr><th scope="row">${ctx.esc(r.group)}</th>
      <td class="num">${pct(r.ownership)}</td><td class="num" style="width:45%">${meter(r.share)} ${prob(r.share)}</td></tr>`).join("")}</tbody></table></div>`;
  }

  function renderConcentration(d, ctx) {
    const o = d.ownership_model, c = o.concentration;
    const tiles = ["5", "10", "20"].map((n) => `<div class="own-tile"><div class="dm-muted">Top ${n} players</div><div class="own-tile-v">${pct(c.top[n].ownership)}</div><div class="dm-muted">${prob(c.top[n].share)} of all roster spots</div></div>`).join("");
    return ctx.card(`G. Ownership concentration ${tag("BAYESIAN POSTERIOR")}`,
        ctx.note(`Summed posterior ownership. A Classic lineup has 9 spots, so the field's ownership totals ${pct(c.total_roster_pct)} (900% by construction, less rounding and players not shown).`)
        + `<div class="own-tiles">${tiles}</div><div class="own-shares">${shareTable("By position", c.position, ctx)}${shareTable("By team", c.team, ctx)}${shareTable("By game", c.game, ctx)}${shareTable("By salary range", c.salary, ctx)}</div>`, "dm-wide")
      + ctx.card(`Chalk distribution ${tag("BAYESIAN POSTERIOR")}`, ctx.note("Players in each posterior ownership range.") + barChart(o.chalk_distribution, ctx)
        + `<table class="dm-table visually-hidden"><tbody>${o.chalk_distribution.map((b) => `<tr><th>${b.range}</th><td>${b.count}</td></tr>`).join("")}</tbody></table>`);
  }

  // ------------------------------------------------------------ H / 14
  function dupTable(dup, ctx) {
    const rows = Object.entries(dup.lineups || {}).map(([label, x]) => x.error ? `<tr><th scope="row">${ctx.esc(label)}</th><td colspan="6" class="dm-muted">${ctx.esc(x.error)}</td></tr>`
      : `<tr><th scope="row">${ctx.esc(label)}</th><td class="num">${x.expected_duplicates < 0.001 ? x.expected_duplicates.toExponential(1) : x.expected_duplicates.toFixed(3)}</td>
        <td class="num">${x.p_duplicated < 0.001 ? "<0.1%" : prob(x.p_duplicated)}</td><td class="num">${x.expected_share_5.toFixed(1)}</td>
        <td class="num">${x.expected_share_6.toFixed(1)}</td><td class="num">${x.expected_share_7.toFixed(1)}</td><td class="num">${x.uniqueness_pct.toFixed(0)}</td></tr>`).join("");
    return `<div class="dm-table-wrap"><table class="dm-table own-num-heads"><thead><tr><th scope="col">Lineup</th><th scope="col">Expected duplicates</th><th scope="col">P(duplicated)</th><th scope="col">Expected entries sharing 5+</th><th scope="col">6+</th><th scope="col">7+</th><th scope="col" title="Share of simulated field lineups that are more likely than this one (higher = more unique)">Uniqueness pct</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function levTable(rows, ctx, who) {
    return `<div class="dm-table-wrap"><table class="dm-table own-num-heads"><thead><tr><th scope="col">Player</th><th scope="col">Field (posterior)</th><th scope="col">${who} exposure</th><th scope="col">Field - exposure</th><th scope="col">Exposure / field</th></tr></thead><tbody>
      ${rows.slice(0, 30).map((r) => `<tr><th scope="row">${ctx.esc(r.name)} <span class="dm-muted">${ctx.esc(r.position)}</span></th><td class="num">${pct(r.field)}</td><td class="num">${pct(r.exposure)}</td>
        <td class="num">${r.leverage > 0 ? "+" : ""}${r.leverage.toFixed(1)}</td><td class="num">${r.relative == null ? "-" : r.relative.toFixed(2) + "x"}</td></tr>`).join("")}</tbody></table></div>`;
  }

  function renderDup(d, ctx) {
    const o = d.ownership_model, dup = o.duplication;
    const p = dup.params || {};
    return ctx.card(`H. Expected duplication ${tag("SIMULATED")}`,
        ctx.note(`${(dup.simulated_lineups || 0).toLocaleString()} valid field lineups simulated from the ${o.contest_label} posterior (P(valid) ${prob(dup.p_valid)}), with QB/pass-catcher stacking (+${p.stack}), bring-backs (+${p.bring_back}), RB/DST correlation (+${p.rb_dst}), DSTs avoiding the lineup's QB (x${p.dst_vs_qb}) and a $${(p.min_salary || 0).toLocaleString()} minimum spend -- ${o.model_state.field_learned ? "fit to uploaded field lineups" : "assumptions until actual field lineups are uploaded"}. Expected duplicates use the exact probability of drawing the lineup, times ${o.contest_size.toLocaleString()} - 1 entries. Simulated vs posterior ownership differ by ${dup.simulated_vs_posterior_mae} pts on average.`)
        + dupTable(dup, ctx)
        + `<div class="own-mine"><button type="button" class="dm-btn" data-own-mine="1">Check my Lineup Builder lineups</button> <span class="dm-muted" id="own-mine-status">Uses the lineups you built on the Slates page for this slate.</span></div>
        <div id="own-mine-out"></div>`, "dm-wide")
      + ctx.card("14. Ownership leverage vs exposure", ctx.note("Field ownership (posterior) minus exposure across the model's 15 tournament lineups. Positive = you're under the field; relative = exposure / field. Presented as exposure relative to the field, not as good or bad.") + levTable(o.leverage, ctx, "Model lineup"), "dm-wide");
  }

  // ------------------------------------------------------------ J / K
  function renderNews(d, ctx) {
    const o = d.ownership_model, ms = o.model_state;
    const news = o.late_news.map((n) => `<li><b>${ctx.esc(n.name)}</b> (${ctx.esc(n.team)} ${ctx.esc(n.position)}) <span class="dm-muted">${ctx.esc(n.kind)}</span>: ${ctx.esc(n.text)}</li>`).join("");
    const counts = ["VERY HIGH", "HIGH", "MEDIUM", "LOW", "VERY LOW"].map((c) => `<div class="own-tile">${confBadge(c)}<div class="own-tile-v">${ms.confidence_counts[c] || 0}</div></div>`).join("");
    const acc = Object.entries((ms.accuracy || {}).by_contest || {}).map(([c, a]) => `<tr><th scope="row">${ctx.esc(c)}</th><td class="num">${a.n}</td><td class="num">${pct(a.mae * 100, 2)}</td><td class="num">${pct(a.rmse * 100, 2)}</td><td class="num">${pct(a.bias * 100, 2)}</td><td class="num">${prob(a.coverage80)}</td><td class="num">${a.brier["20"]}</td></tr>`).join("");
    const adj = Object.entries(ms.contest_adjust || {}).map(([c, a]) => `<li>${ctx.esc(c)}: logit shift ${a.delta} vs large-field GPP (n ${a.n})</li>`).join("");
    return ctx.card("J. Late-news adjustments", ctx.note("Confirmed DraftKings statuses override every other input (OUT / Doubtful / IR -> ~0%); the behavioral model reallocates their share to teammates automatically, and status changes since the opening snapshot are listed with the teammates whose posterior moved.")
        + (news ? `<ul class="dm-bullets">${news}</ul>` : '<p class="dm-muted">No confirmed news or status changes.</p>'), "dm-wide")
      + ctx.card("K. Model confidence", `<div class="own-tiles">${counts}</div>
        <ul class="dm-bullets">
          <li>Behavioral model (Model C): ${ms.behavioral_trained ? `trained on actual ownership (effective N ${ms.behavioral_n})` : `untrained -- weak default coefficients, N ${ms.behavioral_n}, each position's most-owned player anchored at an assumed typical level`}. Slots: ${Object.entries(ms.slots).map(([k, v]) => `${k} ${v}`).join(", ")}.</li>
          <li>Calibration: ${ms.calibrated ? `isotonic curve from ${ms.calibration_n} graded player-contests` : `not yet (${ms.calibration_n} of 100 graded player-contests needed)`}.</li>
          <li>Slates with actual ownership learned from: ${ms.slates_with_actuals}${ms.learned_at ? ` (last ${new Date(ms.learned_at).toLocaleString()})` : ""}.</li>
          ${adj ? `<li>Contest adjustments:<ul>${adj}</ul></li>` : "<li>Contest adjustments: none learned yet -- non-GPP contests share the GPP estimate with a wider interval.</li>"}
        </ul>
        ${acc ? `<h4>Posterior accuracy vs actual ownership</h4><div class="dm-table-wrap"><table class="dm-table own-num-heads"><thead><tr><th scope="col">Contest</th><th scope="col">n</th><th scope="col">MAE</th><th scope="col">RMSE</th><th scope="col">Bias</th><th scope="col">80% coverage</th><th scope="col">Brier P(&gt;20%)</th></tr></thead><tbody>${acc}</tbody></table></div>` : ""}`, "dm-wide");
  }

  // ----------------------------------------------------------------- add
  function renderAdd(d, ctx) {
    const o = d.ownership_model;
    const opts = Object.entries(o.contests).filter(([k]) => !k.startsWith("showdown")).map(([k, v]) => `<option value="${k}"${k === o.contest ? " selected" : ""}>${ctx.esc(v)}</option>`).join("");
    const fmt = 'One player per line: <code>Name, 23.5</code> or <code>Name, TEAM, 23.5</code> (tabs and % fine; DSTs by team code, e.g. <code>BUF, 8</code>).';
    return `<div class="dm-grid">
      ${ctx.card(`Ownership source ${tag("PROJECTED")}`, `<form data-own-form="source" class="own-form">
        <p class="dm-note">Paste a source's projected ownership (e.g. from a subscription you use). Stored with a timestamp on this server and used for everyone's model -- only paste data you're allowed to share. ${fmt}</p>
        <label>Source name <input name="source" required maxlength="60" placeholder="e.g. MySource" /></label>
        <label>Contest <select name="contest">${opts}</select></label>
        <textarea name="text" rows="8" required spellcheck="false" aria-label="Source ownership lines"></textarea>
        <button type="submit" class="dm-btn">Add source projections</button><span class="own-status" aria-live="polite"></span></form>`)}
      ${ctx.card(`Crowd submission ${tag("CROWDSOURCED")}`, `<form data-own-form="crowd" class="own-form">
        <p class="dm-note">Your own ownership estimates. You're identified by an anonymous id stored in this browser; your weight grows as your past estimates are graded against actual ownership. Optional reasoning after the number: <code>Name, 18, cheap RB1 role</code>.</p>
        <label>Display name (optional) <input name="display_name" maxlength="40" /></label>
        <label>Contest <select name="contest">${opts}</select></label>
        <label>Confidence <select name="confidence"><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option></select></label>
        <textarea name="text" rows="8" required spellcheck="false" aria-label="Crowd ownership lines"></textarea>
        <button type="submit" class="dm-btn">Submit estimates</button><span class="own-status" aria-live="polite"></span></form>`)}
      ${ctx.card(`Actual contest ownership ${tag("ACTUAL")}`, `<form data-own-form="actual" class="own-form">
        <p class="dm-note">After the slate: upload the DraftKings contest-standings CSV (Contest page -> Export lineups). It carries every player's %Drafted and every entry's lineup, so the model learns actual ownership, source/crowd accuracy, calibration, contest differences and how the field stacks. <code>Name, pct</code> lines also work (ownership only).</p>
        <label>Contest <select name="contest">${opts}</select></label>
        <input type="file" name="file" accept=".csv,text/csv" aria-label="DraftKings contest standings CSV" />
        <textarea name="text" rows="4" spellcheck="false" placeholder="...or paste Name, pct lines" aria-label="Actual ownership lines"></textarea>
        <button type="submit" class="dm-btn">Upload actual ownership</button><span class="own-status" aria-live="polite"></span></form>`)}
    </div>`;
  }

  // --------------------------------------------------------------- entry
  const RENDER = { table: renderTable, ranks: renderRanks, movement: renderMovement, sources: renderSources, crowd: renderCrowd,
    concentration: renderConcentration, dup: renderDup, news: renderNews, add: renderAdd };

  function render(d, ctx) {
    if (!d.ownership_model) return '<p class="dm-muted">Ownership model unavailable.</p>';
    return banner(d, ctx) + subnav() + (RENDER[view.sub] || renderTable)(d, ctx);
  }

  function crowdId() {
    try {
      let id = localStorage.getItem("dfsriches:crowdUserId");
      if (!id) {
        id = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now()).replace(/-/g, "");
        localStorage.setItem("dfsriches:crowdUserId", id);
      }
      return id;
    } catch (e) {
      return "anon" + Date.now();
    }
  }

  const postJson = (url, body) => DFS.getJson(url, null, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

  function click(e, ctx) {
    const t = e.target;
    const sub = t.closest("[data-own-sub]");
    if (sub) { view.sub = sub.dataset.ownSub; ctx.rerender(); return true; }
    const pos = t.closest("[data-own-pos]");
    if (pos) { view.pos = pos.dataset.ownPos; ctx.rerender(); return true; }
    const sort = t.closest("[data-own-sort]");
    if (sort) {
      const k = sort.dataset.ownSort;
      view.sort = { key: k, dir: view.sort.key === k ? -view.sort.dir : (k === "name" || k === "position" ? 1 : -1) };
      ctx.rerender();
      return true;
    }
    const open = t.closest("[data-own-open]");
    if (open) { view.open = view.open === open.dataset.ownOpen ? null : open.dataset.ownOpen; ctx.rerender(); return true; }
    if (t.closest("[data-own-apply]")) {
      const contest = document.getElementById("own-contest").value;
      const size = Number(document.getElementById("own-size").value) || null;
      ctx.reload({ contest, contestSize: size });
      return true;
    }
    if (t.closest("[data-own-mine]")) { checkMine(ctx); return true; }
    return false;
  }

  async function checkMine(ctx) {
    const status = document.getElementById("own-mine-status");
    const out = document.getElementById("own-mine-out");
    const s = ctx.state;
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(`dfsriches:lineups:${s.season}:${s.week}:${s.slate}`) || "null"); } catch (e) { saved = null; }
    const lineups = saved && Array.isArray(saved.lineups) ? saved.lineups.filter((lu) => Array.isArray(lu) && lu.length === 9 && lu.every((x) => x != null)) : [];
    if (!lineups.length) {
      status.textContent = "No complete lineups saved for this slate in the Lineup Builder (Slates page).";
      return;
    }
    status.textContent = `Simulating ${lineups.length} lineup${lineups.length === 1 ? "" : "s"}...`;
    try {
      const o = ctx.state.data.ownership_model;
      const r = await postJson("/api/ownership/duplication", { season: s.season, week: s.week, slate_id: s.slate, contest: o.contest, contest_size: o.contest_size, lineups });
      status.textContent = `Your lineups at ${r.contest_size.toLocaleString()} entries:`;
      out.innerHTML = dupTable(r.duplication, ctx) + "<h4>Your exposure vs the field</h4>" + levTable(r.leverage, ctx, "Your");
    } catch (err) {
      status.textContent = "Could not simulate: " + err.message;
    }
  }

  async function submit(e, ctx) {
    const form = e.target.closest("[data-own-form]");
    if (!form) return false;
    e.preventDefault();
    const kind = form.dataset.ownForm;
    const status = form.querySelector(".own-status");
    const s = ctx.state;
    const fd = new FormData(form);
    const body = { season: s.season, week: s.week, slate_id: s.slate, contest: fd.get("contest"), text: fd.get("text") || "" };
    try {
      if (kind === "source") body.source = fd.get("source");
      if (kind === "crowd") Object.assign(body, { user_id: crowdId(), display_name: fd.get("display_name"), confidence: Number(fd.get("confidence")) });
      if (kind === "actual") {
        const file = form.querySelector('input[type=file]').files[0];
        if (file) body.text = await file.text();
      }
      if (!String(body.text).trim()) throw new Error("Nothing to submit");
      status.textContent = kind === "actual" ? "Uploading and relearning..." : "Saving...";
      const r = await postJson(`/api/ownership/${kind}`, body);
      status.textContent = `Saved ${r.added} player${r.added === 1 ? "" : "s"}${r.unmatched && r.unmatched.length ? `; not matched: ${r.unmatched.slice(0, 8).join(", ")}${r.unmatched.length > 8 ? "..." : ""}` : ""}${r.field_lineups != null ? `; ${r.field_lineups} field lineups` : ""}. Recalculating...`;
      form.reset();
      ctx.reload({});
    } catch (err) {
      status.textContent = "Error: " + err.message;
    }
    return true;
  }

  function input(e, ctx) {
    if (e.target.id !== "own-search") return false;
    view.q = e.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      const cur = document.getElementById("own-search");
      const pos = cur ? cur.selectionStart : view.q.length;
      ctx.rerender();
      const again = document.getElementById("own-search");
      if (again) { again.focus(); again.setSelectionRange(pos, pos); }
    }, 120);
    return true;
  }

  window.DFSOwnership = { render, click, submit, input };
})();
