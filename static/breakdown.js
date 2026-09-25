(function () {
  "use strict";

  const gamesEl = document.getElementById("breakdown-games");
  const emptyStateEl = document.getElementById("breakdown-empty-state");
  const weekLabelEl = document.getElementById("breakdown-week-label");
  const dialogEl = document.getElementById("game-detail");
  const dialogTitleEl = document.getElementById("gd-title");
  const dialogBodyEl = document.getElementById("gd-body");
  const tooltipEl = document.getElementById("gd-tooltip");

  const state = { season: null, week: null };

  const escapeHtml = DFS.esc;
  const fmtSalary = DFS.money;

  function fmtNum(v, decimals) {
    if (v == null) return "-";
    return v.toFixed(decimals == null ? 1 : decimals);
  }

  function fmtPct(v) {
    if (v == null) return "-";
    return Math.round(v * 100) + "%";
  }

  function fmtSigned(v) {
    if (v == null) return "-";
    const p = Math.round(v * 100);
    return (p > 0 ? "+" : "") + p + "%";
  }

  function fmtRank(r) {
    return r == null ? "" : ` <span class="rank-pill">#${r}</span>`;
  }

  function statRow(label, awayVal, awayRank, homeVal, homeRank, fmt) {
    fmt = fmt || fmtNum;
    return `
      <tr>
        <td class="stat-label">${label}</td>
        <td class="num">${fmt(awayVal)}${fmtRank(awayRank)}</td>
        <td class="num">${fmt(homeVal)}${fmtRank(homeRank)}</td>
      </tr>
    `;
  }

  function renderTargets(players, maxReasons) {
    if (!players || players.length === 0) {
      return '<span class="no-players">No salary data posted yet</span>';
    }
    return players
      .map(
        (p) => `
          <div class="target">
            <div class="target-line">
              <span class="tp-pos">${escapeHtml(p.position)}</span>
              <span class="target-name">${escapeHtml(p.name)}</span>
              ${p.role === "Value" ? '<span class="target-role">Value</span>' : ""}
              <span class="tp-salary">${fmtSalary(p.salary)}</span>
              ${p.proj_points != null ? `<span class="target-proj" title="DK points from the projected stat line, matchup-adjusted">Proj ${p.proj_points.toFixed(1)}</span>` : ""}
              ${p.ceiling != null ? `<span class="target-ceiling" title="Matchup-adjusted ceiling">Ceil ${p.ceiling.toFixed(1)}</span>` : ""}
            </div>
            <ul class="target-reasons">${(p.reasons || []).slice(0, maxReasons).map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
          </div>`
      )
      .join("");
  }

  // --- postgame (app/postgame.py) ---
  const VERDICT_CLS = { Expected: "pg-v-expected", "Favorite won": "pg-v-fav", "Coin flip": "pg-v-flip", "Mild upset": "pg-v-mild", Upset: "pg-v-upset" };

  function verdictTags(pred) {
    return `<span class="pg-verdict ${VERDICT_CLS[pred.verdict] || "pg-v-flip"}">${escapeHtml(pred.verdict)}</span>`
      + (pred.surprises || []).map((t) => `<span class="pg-tag">${escapeHtml(t)}</span>`).join("");
  }

  function renderPostgameCard(pg) {
    if (!pg) return "";
    const pred = pg.predictability || {};
    const items = [...pg.result, ...pg.flow.slice(1, 2), ...pg.exploited.slice(0, 1), ...pg.struggled.slice(0, 1), ...(pred.text || []).slice(0, 1)];
    return `<div class="pg-card">
        <div class="pg-top"><span class="pg-label">Postgame</span>${verdictTags(pred)}</div>
        <div class="pg-headline">${escapeHtml(pg.headline)}</div>
        <ul class="pg-list">${items.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ul>
        ${pg.note ? `<p class="pg-note">${escapeHtml(pg.note)}</p>` : ""}
      </div>`;
  }

  function renderGameCard(gb) {
    const g = gb.game;
    const away = gb.away_stats;
    const home = gb.home_stats;

    const card = document.createElement("article");
    card.className = "breakdown-card";
    card.innerHTML = `
      <header class="breakdown-card-header">
        <div>
          <div class="matchup">${escapeHtml(g.away)} @ ${escapeHtml(g.home)}</div>
          <div class="meta">${escapeHtml(g.kickoff_et)}${g.network ? " &middot; " + escapeHtml(g.network) : ""}${gb.postgame ? ` &middot; <b>Final: ${escapeHtml(g.away)} ${g.context.away_score}, ${escapeHtml(g.home)} ${g.context.home_score}</b>` : ""}</div>
        </div>
        <button type="button" class="gd-open" data-game="${escapeHtml(g.game_id)}">${gb.postgame ? "Game recap" : "Advanced matchup"} &rarr;</button>
      </header>
      ${renderPostgameCard(gb.postgame)}

      <div class="table-scroll">
        <table class="breakdown-stat-table">
          <thead>
            <tr>
              <th scope="col" title="Last 8 games; tempo and pass rates are season-to-date once a team has 2+ games">Metric</th>
              <th scope="col" class="num">${escapeHtml(g.away)}</th>
              <th scope="col" class="num">${escapeHtml(g.home)}</th>
            </tr>
          </thead>
          <tbody>
            ${statRow("Points/gm", away.points_for, away.points_for_rank, home.points_for, home.points_for_rank)}
            ${statRow("Points allowed/gm", away.points_against, away.points_against_rank, home.points_against, home.points_against_rank)}
            ${statRow("Yards/play", away.yards_per_play, away.yards_per_play_rank, home.yards_per_play, home.yards_per_play_rank, (v) => fmtNum(v, 2))}
            ${statRow("Yards/play allowed", away.yards_allowed_per_play, away.yards_allowed_per_play_rank, home.yards_allowed_per_play, home.yards_allowed_per_play_rank, (v) => fmtNum(v, 2))}
            ${statRow("Neutral tempo (sec/snap)", away.tempo_secs, away.tempo_rank, home.tempo_secs, home.tempo_rank, (v) => fmtNum(v, 1))}
            ${statRow("Plays/gm (volume)", away.plays_per_game, away.plays_rank, home.plays_per_game, home.plays_rank, (v) => fmtNum(v, 0))}
            ${statRow("Neutral pass rate", away.pass_pct, null, home.pass_pct, null, fmtPct)}
            ${statRow("Neutral pass rate faced (D)", away.opp_pass_pct_allowed, away.opp_pass_pct_allowed_rank, home.opp_pass_pct_allowed, home.opp_pass_pct_allowed_rank, fmtPct)}
            ${statRow("Neutral rush rate faced (D)", away.opp_rush_pct_allowed, away.opp_rush_pct_allowed_rank, home.opp_rush_pct_allowed, home.opp_rush_pct_allowed_rank, fmtPct)}
          </tbody>
        </table>
      </div>

      <ul class="breakdown-takeaways">
        ${gb.takeaways.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}
      </ul>

      <div class="breakdown-top-players">
        <div class="tp-team">
          <span class="tp-team-label">${escapeHtml(g.away)} targets</span>
          <div class="tp-list">${renderTargets(gb.away_top_players, 2)}</div>
        </div>
        <div class="tp-team">
          <span class="tp-team-label">${escapeHtml(g.home)} targets</span>
          <div class="tp-list">${renderTargets(gb.home_top_players, 2)}</div>
        </div>
      </div>
    `;
    return card;
  }

  // --- game detail: small DOM helpers (all data goes in via textContent) ---

  function el(tag, opts, children) {
    const node = document.createElement(tag);
    opts = opts || {};
    if (opts.cls) node.className = opts.cls;
    if (opts.text != null) node.textContent = opts.text;
    if (opts.style) Object.assign(node.style, opts.style);
    if (opts.tip) {
      node.dataset.tip = opts.tip;
      node.tabIndex = 0;
    }
    if (opts.attrs) for (const [k, v] of Object.entries(opts.attrs)) node.setAttribute(k, v);
    for (const c of children || []) if (c) node.appendChild(c);
    return node;
  }

  function teamKey(team, g) {
    return team === g.away ? "a" : "b";
  }

  function legend(g) {
    return el("div", { cls: "gd-legend", attrs: { "aria-label": "Team colors" } }, [
      el("span", { cls: "gd-legend-item" }, [el("span", { cls: "gd-swatch team-a" }), el("span", { text: `${g.away} (away)` })]),
      el("span", { cls: "gd-legend-item" }, [el("span", { cls: "gd-swatch team-b" }), el("span", { text: `${g.home} (home)` })]),
    ]);
  }

  function section(title, subtitle, chart, insight, table) {
    const children = [el("h3", { text: title })];
    if (subtitle) children.push(el("p", { cls: "gd-sub", text: subtitle }));
    if (chart) children.push(chart);
    if (insight) children.push(el("p", { cls: "gd-insight" }, [el("strong", { text: "What it means: " }), document.createTextNode(insight)]));
    if (table) children.push(table);
    return el("section", { cls: "gd-section" }, children);
  }

  function dataTable(headers, rows) {
    const thead = el("thead", {}, [el("tr", {}, headers.map((h) => el("th", { text: h, attrs: { scope: "col" } })))]);
    const tbody = el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", { text: c })))));
    return el("details", { cls: "gd-table" }, [el("summary", { text: "View as table" }), el("table", {}, [thead, tbody])]);
  }

  // Diverging bars around a center reference (league average = 0).
  function divergingChart(rows, domain, centerLabel) {
    const chart = el("div", { cls: "gd-chart gd-diverging" });
    for (const r of rows) {
      const v = Math.max(-domain, Math.min(domain, r.value));
      const w = (Math.abs(v) / domain) * 50;
      const bar = el("div", {
        cls: `gd-bar ${r.muted ? "muted" : "team-" + r.team} ${v >= 0 ? "pos" : "neg"}`,
        style: v >= 0 ? { left: "50%", width: w + "%" } : { left: 50 - w + "%", width: w + "%" },
        tip: r.tip,
      });
      chart.appendChild(
        el("div", { cls: "gd-row" }, [
          el("span", { cls: "gd-label", text: r.label }),
          el("div", { cls: "gd-track" }, [el("span", { cls: "gd-center" }), bar]),
          el("span", { cls: "gd-value", text: r.valueText }),
        ])
      );
    }
    chart.appendChild(el("div", { cls: "gd-axis" }, [el("span"), el("span", { cls: "gd-axis-center", text: centerLabel }), el("span")]));
    return chart;
  }

  // Dots on a league min..max track (e.g. slowest -> fastest), with a league-average tick.
  function rangeChart(rows, g) {
    const chart = el("div", { cls: "gd-chart gd-range" });
    for (const r of rows) {
      const pos = (v) => {
        const t = (v - r.min) / (r.max - r.min || 1);
        return Math.max(0, Math.min(1, r.invert ? 1 - t : t)) * 100;
      };
      const track = el("div", { cls: "gd-range-track" }, [
        el("span", { cls: "gd-range-avg", style: { left: pos(r.avg) + "%" }, tip: `League average: ${r.fmt(r.avg)}` }),
        ...r.points.map((p) =>
          el("span", { cls: `gd-dot team-${teamKey(p.team, g)}`, style: { left: pos(p.value) + "%" }, tip: `${p.team}: ${r.fmt(p.value)}${p.rank ? ` (#${p.rank})` : ""}` })
        ),
      ]);
      chart.appendChild(
        el("div", { cls: "gd-range-row" }, [
          el("div", { cls: "gd-range-head" }, [
            el("span", { cls: "gd-label", text: r.label }),
            el("span", { cls: "gd-range-values", text: r.points.map((p) => `${p.team} ${r.fmt(p.value)}${p.rank ? ` (#${p.rank})` : ""}`).join("  ·  ") }),
          ]),
          track,
          el("div", { cls: "gd-range-ends" }, [el("span", { text: r.leftLabel }), el("span", { text: r.rightLabel })]),
        ])
      );
    }
    return chart;
  }

  // Share meters (0-100%) with a league-average tick.
  function meterChart(rows) {
    const chart = el("div", { cls: "gd-chart gd-meters" });
    for (const r of rows) {
      const fill = el("div", { cls: `gd-meter-fill team-${r.team}`, style: { width: Math.round(r.value * 100) + "%" }, tip: r.tip });
      const track = el("div", { cls: `gd-meter team-${r.team}` }, [fill]);
      if (r.avg != null) track.appendChild(el("span", { cls: "gd-meter-avg", style: { left: r.avg * 100 + "%" }, tip: `League average: ${fmtPct(r.avg)}` }));
      chart.appendChild(el("div", { cls: "gd-row" }, [el("span", { cls: "gd-label", text: r.label }), track, el("span", { cls: "gd-value", text: r.valueText })]));
    }
    return chart;
  }

  // Usage: share of team targets + carries, bar = last 3 games, tick = last 8.
  function usageChart(rows, team, maxShare) {
    const chart = el("div", { cls: "gd-chart gd-usage" });
    for (const u of rows) {
      const track = el("div", { cls: "gd-track plain" }, [
        el("div", {
          cls: `gd-bar team-${team} pos`,
          style: { left: "0%", width: (u.share_l3 / maxShare) * 100 + "%" },
          tip: `${u.name}: ${fmtPct(u.share_l3)} last 3 games${u.share_l8 != null ? `, ${fmtPct(u.share_l8)} last 8` : ""}`,
        }),
      ]);
      if (u.share_l8 != null) track.appendChild(el("span", { cls: "gd-tick", style: { left: (u.share_l8 / maxShare) * 100 + "%" } }));
      const name = `${u.position} ${u.name}${u.injury !== "Healthy" ? ` (${u.injury})` : ""}`;
      chart.appendChild(el("div", { cls: "gd-row" }, [el("span", { cls: "gd-label", text: name }), track, el("span", { cls: "gd-value", text: fmtPct(u.share_l3) })]));
    }
    return chart;
  }

  function statTile(label, value, sub) {
    return el("div", { cls: "gd-tile" }, [el("span", { cls: "gd-tile-label", text: label }), el("span", { cls: "gd-tile-value", text: value }), sub ? el("span", { cls: "gd-tile-sub", text: sub }) : null]);
  }

  function ordinal(n) {
    const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th";
    return n + s;
  }

  // Line play, efficiency and scheme tendencies (app/trenches.py).
  const EDGE_LABELS = { protection: ["protection", "pass rush"], run: ["run blocking", "run defense"], pass: ["dropback offense", "pass defense"] };
  const TRENCH_ROWS = [
    ["Offense", null],
    ["Success rate", (t) => t.off.success, "pct"], ["EPA/play", (t) => t.off.epa_play, "epa"],
    ["Sack rate", (t) => t.off.sack_rate, "pct"], ["Sack + QB-hit rate", (t) => t.off.pressure_rate, "pct"],
    ["Explosive pass rate (20+)", (t) => t.off.explosive_pass, "pct"], ["Rush success rate", (t) => t.off.rush_success, "pct"],
    ["Run stuff rate (0 or less)", (t) => t.off.stuff_rate, "pct"], ["Explosive run rate (10+)", (t) => t.off.explosive_run, "pct"],
    ["Play-action rate", (t) => t.off.play_action, "pct"], ["Motion rate", (t) => t.off.motion, "pct"],
    ["Screen rate", (t) => t.off.screen, "pct"], ["RPO rate", (t) => t.off.rpo, "pct"], ["No-huddle rate", (t) => t.off.no_huddle, "pct"],
    ["Runs vs light box (6 or fewer)", (t) => t.off.light_box, "pct"],
    ["Defense", null],
    ["Success rate allowed", (t) => t.def.success, "pct"], ["EPA/play allowed", (t) => t.def.epa_play, "epa"],
    ["Sack rate", (t) => t.def.sack_rate, "pct"], ["Sack + QB-hit rate", (t) => t.def.pressure_rate, "pct"],
    ["Blitz rate", (t) => t.def.blitz, "pct"], ["Avg pass rushers", (t) => t.def.rushers, "dec"],
    ["Rush success allowed", (t) => t.def.rush_success, "pct"], ["Run stuff rate", (t) => t.def.stuff_rate, "pct"],
    ["Heavy box rate (8+)", (t) => t.def.heavy_box, "pct"],
    ["Coverage", null],
    ["Man coverage rate", (t) => t.cov.man, "pct"], ["Single-high shell", (t) => t.cov.single_high, "pct"],
    ["Two-high shell", (t) => t.cov.two_high, "pct"], ["Most-used coverage", (t) => t.cov.top_shell, "text"],
    ["Pressure rate (NGS)", (t) => t.cov.true_pressure, "pct"], ["Offense: pressure allowed (NGS)", (t) => t.cov.pressure_allowed, "pct"],
    ["Offense: time to throw", (t) => t.cov.time_to_throw, "sec"],
  ];

  function fmtTrench(v, kind) {
    if (v == null || v === "") return "-";
    if (kind === "pct") return fmtPct(v);
    if (kind === "epa") return (v > 0 ? "+" : "") + v.toFixed(3);
    if (kind === "sec") return v.toFixed(2) + "s";
    if (kind === "dec") return v.toFixed(2);
    return String(v);
  }

  function trenchSection(t, g) {
    const rows = [];
    for (const m of [t.away_offense, t.home_offense]) {
      for (const [key, e] of Object.entries(m.edges)) {
        const [ou, du] = EDGE_LABELS[key];
        rows.push({
          label: `${m.offense} ${ou} (${ordinal(e.offense_rank)}) vs ${m.defense} ${du} (${ordinal(e.defense_rank)})`,
          value: e.edge, team: teamKey(m.offense, g), muted: e.strength === "neutral",
          valueText: `${e.edge > 0 ? "+" : ""}${e.edge.toFixed(1)}`,
          tip: `${m.offense} ${ou} ranks ${ordinal(e.offense_rank)}; ${m.defense} ${du} ranks ${ordinal(e.defense_rank)}. Edge = difference in league z-scores; gray = no real edge.`,
        });
      }
    }
    const notes = [...t.away_offense.notes, ...t.home_offense.notes].filter((n) => !t.insight.includes(n));
    const league = (fn) => { try { return fn({ off: t.league.off || {}, def: t.league.def || {}, cov: t.league.cov || {} }); } catch (e) { return null; } };
    const units = Object.keys(t.away.units).map((u) => [t.away.units[u].label, `#${t.away.units[u].rank}`, `#${t.home.units[u].rank}`, "-"]);
    const tableRows = [["Unit grades (1 = best)", null], ...units.map((u) => [u[0], () => u]), ...TRENCH_ROWS];
    const tbody = el("tbody", {}, tableRows.map(([label, fn, kind]) => {
      if (!fn) return el("tr", { cls: "gd-group" }, [el("th", { text: label + (label === "Coverage" && t.coverage_season ? ` (${t.coverage_season} season)` : ""), attrs: { scope: "colgroup", colspan: "4" } })]);
      const vals = kind ? [fmtTrench(fn(t.away), kind), fmtTrench(fn(t.home), kind), fmtTrench(league(fn), kind)] : fn().slice(1);
      return el("tr", {}, [el("th", { text: label, attrs: { scope: "row" } }), ...vals.map((v) => el("td", { text: v }))]);
    }));
    const thead = el("thead", {}, [el("tr", {}, ["Metric", g.away, g.home, "League"].map((h) => el("th", { text: h, attrs: { scope: "col" } })))]);
    const table = el("div", { cls: "gd-trench-wrap", attrs: { tabindex: "0", role: "region", "aria-label": "Line play and scheme table" } },
      [el("table", { cls: "gd-trench-table" }, [thead, tbody])]);
    const refs = el("p", { cls: "gd-sub" }, [document.createTextNode(`${t.window}. Sources: ${t.sources.join(", ")}. ${t.note} Compare: `)]);
    t.references.forEach((r, i) => {
      refs.appendChild(el("a", { text: r.label, attrs: { href: r.url, target: "_blank", rel: "noopener noreferrer" } }));
      if (i < t.references.length - 1) refs.appendChild(document.createTextNode(" · "));
    });
    const extra = notes.length ? el("ul", { cls: "gd-notes" }, notes.map((n) => el("li", { text: n }))) : null;
    return el("section", { cls: "gd-section" }, [
      el("h3", { text: "Trenches, efficiency and schemes" }),
      el("p", { cls: "gd-sub", text: "Each offense unit vs the defense unit it faces. Bars to the right favor the offense; gray = no real edge. Competitive plays only (win probability 10-90%)." }),
      rows.length ? divergingChart(rows, 2.5, "Even matchup") : null,
      el("p", { cls: "gd-insight" }, [el("strong", { text: "What it means: " }), document.createTextNode(t.insight)]),
      extra, table, refs,
    ]);
  }

  function bulletList(items) {
    return el("ul", { cls: "gd-notes" }, items.map((t) => el("li", { text: t })));
  }

  function postgameSection(pg, g) {
    const pred = pg.predictability || {};
    const c = g.context;
    const parts = [el("h3", { text: "Postgame: how it played out" })];
    const tags = el("div", { cls: "pg-top" });
    tags.innerHTML = verdictTags(pred);
    parts.push(tags);
    parts.push(el("div", { cls: "gd-tiles" }, [
      statTile("Final", `${g.away} ${c.away_score}, ${g.home} ${c.home_score}`),
      pred.line_win_prob != null ? statTile(`${pred.winner} pregame win prob`, fmtPct(pred.line_win_prob), "closing line") : null,
      pred.margin_miss != null ? statTile("Margin vs spread", `${pred.margin_miss} pts`, pred.margin_miss_share != null ? `${fmtPct(pred.margin_miss_share)} of games miss by as much` : null) : null,
      pred.total_miss != null ? statTile("Total vs line", `${pred.total_miss} pts`, pred.total_miss_share != null ? `${fmtPct(pred.total_miss_share)} of games miss by as much` : null) : null,
    ]));
    parts.push(el("p", { cls: "gd-insight" }, [el("strong", { text: pg.headline + " " }), document.createTextNode(pg.result.join(" "))]));
    if (pg.flow.length) parts.push(bulletList(pg.flow));
    const ts = pg.team_stats || {};
    const A = ts[g.away], H = ts[g.home];
    if (A && H) {
      const rows = [
        ["Plays", (t) => t.plays], ["Success rate", (t) => (t.success != null ? fmtPct(t.success) : null)],
        ["EPA/play", (t) => (t.epa_play != null ? fmtSigned2(t.epa_play) : null)], ["Dropback EPA/play", (t) => (t.db_epa != null ? fmtSigned2(t.db_epa) : null)],
        ["Rush EPA/play", (t) => (t.rush_epa != null ? fmtSigned2(t.rush_epa) : null)], ["Yards/play", (t) => t.yards_per_play],
        ["Explosive plays", (t) => t.explosive], ["Sacks taken", (t) => t.sacks_taken], ["Turnovers", (t) => t.turnovers],
      ].filter(([, f]) => f(A) != null || f(H) != null);
      const thead = el("thead", {}, [el("tr", {}, ["Metric", g.away, g.home].map((h) => el("th", { text: h, attrs: { scope: "col" } })))]);
      const tbody = el("tbody", {}, rows.map(([label, f]) => el("tr", {}, [el("th", { text: label, attrs: { scope: "row" } }), el("td", { text: String(f(A) ?? "-") }), el("td", { text: String(f(H) ?? "-") })])));
      parts.push(el("div", { cls: "gd-trench-wrap", attrs: { tabindex: "0", role: "region", "aria-label": "Game stats" } }, [el("table", { cls: "gd-trench-table" }, [thead, tbody])]));
    }
    if (pg.matchups.length) {
      parts.push(el("h4", { text: "Matchups: pregame expectation vs what happened" }));
      parts.push(el("p", { cls: "gd-sub", text: "Expected = the offense's pregame rate + the defense's pregame rate allowed - league average (competitive plays). Bars to the right mean the offense beat that expectation; gray = within one standard error (played to form)." }));
      parts.push(divergingChart(pg.matchups.map((m) => ({
        label: m.label, value: m.better * m.z, team: teamKey(m.offense, g), muted: m.verdict === "to form",
        valueText: `${fmtPct(m.actual)} vs ${fmtPct(m.expected)}`,
        tip: m.text,
      })), 3, "As expected"));
      const called = pg.matchups.filter((m) => m.verdict !== "to form" || m.call).map((m) => m.text);
      if (called.length) parts.push(bulletList(called));
      parts.push(dataTable(["Matchup", "Attempts", "Actual", "Expected", "League", "Pregame edge", "Verdict", "Pregame call"], pg.matchups.map((m) => [
        m.label, String(m.attempts), fmtPct(m.actual), fmtPct(m.expected), fmtPct(m.league),
        m.pregame ? `${m.pregame.edge > 0 ? "+" : ""}${m.pregame.edge.toFixed(1)} (${m.pregame.strength})` : "-", m.verdict, m.call || "-"])));
    }
    parts.push(el("h4", { text: "How predictable was this?" }));
    parts.push(bulletList(pred.text || []));
    const dfs = pg.dfs;
    if (dfs) {
      parts.push(el("h4", { text: "DFS results" }));
      if (dfs.text) parts.push(el("p", { cls: "gd-sub", text: dfs.text }));
      const top = dfs.top_scorers.map((p) => [p.name, p.team, p.position, p.points.toFixed(1), fmtSalary(p.salary), p.value != null ? p.value.toFixed(2) : "-"]);
      if (top.length) {
        const thead = el("thead", {}, [el("tr", {}, ["Top scorers", "Team", "Pos", "DK pts", "Salary", "Pts/$1k"].map((h) => el("th", { text: h, attrs: { scope: "col" } })))]);
        const tbody = el("tbody", {}, top.map((r) => el("tr", {}, [el("th", { text: r[0], attrs: { scope: "row" } }), ...r.slice(1).map((v) => el("td", { text: v }))])));
        parts.push(el("div", { cls: "gd-trench-wrap", attrs: { tabindex: "0", role: "region", "aria-label": "Top DraftKings scorers" } }, [el("table", { cls: "gd-trench-table" }, [thead, tbody])]));
      }
      if (dfs.targets.length) {
        const thead = el("thead", {}, [el("tr", {}, ["Pregame target", "Team", "Proj", "Ceiling", "Actual", "Result"].map((h) => el("th", { text: h, attrs: { scope: "col" } })))]);
        const tbody = el("tbody", {}, dfs.targets.map((t) => el("tr", {}, [
          el("th", { text: `${t.name} (${t.position})`, attrs: { scope: "row" } }), el("td", { text: t.team }),
          el("td", { text: t.proj != null ? t.proj.toFixed(1) : "-" }), el("td", { text: t.ceiling != null ? t.ceiling.toFixed(1) : "-" }),
          el("td", { text: t.points.toFixed(1) }), el("td", { cls: t.result === "Missed" ? "pg-miss" : "pg-hit", text: t.result })])));
        parts.push(el("div", { cls: "gd-trench-wrap", attrs: { tabindex: "0", role: "region", "aria-label": "Pregame targets graded" } }, [el("table", { cls: "gd-trench-table" }, [thead, tbody])]));
      }
      if (dfs.note) parts.push(el("p", { cls: "gd-sub", text: dfs.note }));
    }
    if (pg.note) parts.push(el("p", { cls: "gd-sub", text: pg.note }));
    parts.push(el("p", { cls: "gd-sub", text: "The sections below show the matchup as it looked before kickoff (stats entering the week)." }));
    return el("section", { cls: "gd-section pg-section" }, parts);
  }

  function fmtSigned2(v) {
    return (v > 0 ? "+" : "") + v.toFixed(2);
  }

  function renderDetail(d) {
    const gb = d.breakdown;
    const g = gb.game;
    const a = gb.away_stats;
    const h = gb.home_stats;
    const L = d.league;
    const c = g.context || {};
    const body = [];

    dialogTitleEl.textContent = `${g.away} @ ${g.home}`;
    body.push(el("p", { cls: "gd-meta", text: `${g.kickoff_et}${g.network ? " · " + g.network : ""} · stats entering Week ${g.week}` }));
    body.push(legend(g));
    if (gb.postgame) body.push(postgameSection(gb.postgame, g));

    // Vegas
    const tiles = el("div", { cls: "gd-tiles" }, [
      c.home_spread != null
        ? statTile("Spread", c.home_spread === 0 ? "Pick'em" : `${c.home_spread < 0 ? g.home : g.away} -${Math.abs(c.home_spread)}`)
        : null,
      c.total_line != null ? statTile("Total", String(c.total_line), gb.total_rank_this_week ? `${ordinal(gb.total_rank_this_week)} highest this week` : null) : null,
      c.away_implied_total != null ? statTile(`${g.away} implied`, c.away_implied_total.toFixed(1), gb.away_implied_rank_this_week ? `${ordinal(gb.away_implied_rank_this_week)} of the week` : null) : null,
      c.home_implied_total != null ? statTile(`${g.home} implied`, c.home_implied_total.toFixed(1), gb.home_implied_rank_this_week ? `${ordinal(gb.home_implied_rank_this_week)} of the week` : null) : null,
    ]);
    body.push(section("Vegas outlook", null, tiles, d.insights.vegas));

    // Efficiency, one section per offense
    const effRows = (off, def, offTeam, defTeam) => {
      const rows = [];
      if (off.yards_per_play != null && L.yards_per_play)
        rows.push({ label: `${offTeam} offense: yards/play`, value: off.yards_per_play / L.yards_per_play - 1, team: teamKey(offTeam, g), valueText: `${fmtSigned(off.yards_per_play / L.yards_per_play - 1)} (${off.yards_per_play.toFixed(2)})`, tip: `${offTeam} gains ${off.yards_per_play.toFixed(2)} yards/play; league ${L.yards_per_play.toFixed(2)}` });
      if (def.yards_allowed_per_play != null && L.yards_per_play)
        rows.push({ label: `${defTeam} defense: yards/play allowed`, value: def.yards_allowed_per_play / L.yards_per_play - 1, team: teamKey(defTeam, g), valueText: `${fmtSigned(def.yards_allowed_per_play / L.yards_per_play - 1)} (${def.yards_allowed_per_play.toFixed(2)})`, tip: `${defTeam} allows ${def.yards_allowed_per_play.toFixed(2)} yards/play; league ${L.yards_per_play.toFixed(2)}` });
      if (off.points_for != null && L.points)
        rows.push({ label: `${offTeam} offense: points/game`, value: off.points_for / L.points - 1, team: teamKey(offTeam, g), valueText: `${fmtSigned(off.points_for / L.points - 1)} (${off.points_for.toFixed(1)})`, tip: `${offTeam} scores ${off.points_for.toFixed(1)}/game; league ${L.points.toFixed(1)}` });
      if (def.points_against != null && L.points)
        rows.push({ label: `${defTeam} defense: points allowed`, value: def.points_against / L.points - 1, team: teamKey(defTeam, g), valueText: `${fmtSigned(def.points_against / L.points - 1)} (${def.points_against.toFixed(1)})`, tip: `${defTeam} allows ${def.points_against.toFixed(1)}/game; league ${L.points.toFixed(1)}` });
      return rows;
    };
    for (const [off, def, offTeam, defTeam, key] of [[a, h, g.away, g.home, "away_offense"], [h, a, g.home, g.away, "home_offense"]]) {
      const rows = effRows(off, def, offTeam, defTeam);
      if (!rows.length) continue;
      body.push(section(
        `When ${offTeam} has the ball`,
        "Each bar is vs the league average. Bars to the right favor the offense: it produces more, or the defense allows more.",
        divergingChart(rows, 0.4, "League average"),
        d.insights[key],
        dataTable(["Metric", "vs league avg", "Value"], rows.map((r) => [r.label, fmtSigned(r.value), r.valueText.replace(/^.*\(|\)$/g, "")]))
      ));
    }

    if (d.trenches) body.push(trenchSection(d.trenches, g));

    // Tempo and volume
    if (a.tempo_secs != null && h.tempo_secs != null && L.tempo_min != null) {
      const rows = [
        { label: "Neutral tempo (seconds per snap)", min: L.tempo_min, max: L.tempo_max, avg: L.tempo_secs, invert: true, leftLabel: "Slowest", rightLabel: "Fastest", fmt: (v) => v.toFixed(1) + "s",
          points: [{ team: g.away, value: a.tempo_secs, rank: a.tempo_rank }, { team: g.home, value: h.tempo_secs, rank: h.tempo_rank }] },
      ];
      if (a.plays_per_game != null && h.plays_per_game != null && L.plays_min != null)
        rows.push({ label: "Plays per game (volume)", min: L.plays_min, max: L.plays_max, avg: L.plays, invert: false, leftLabel: "Fewest", rightLabel: "Most", fmt: (v) => v.toFixed(1),
          points: [{ team: g.away, value: a.plays_per_game, rank: a.plays_rank }, { team: g.home, value: h.plays_per_game, rank: h.plays_rank }] });
      body.push(section("Tempo and volume", "Where each team sits between the league's extremes; the thin line is the league average.", rangeChart(rows, g), d.insights.tempo,
        dataTable(["Metric", g.away, g.home, "League avg"], rows.map((r) => [r.label, r.fmt(r.points[0].value), r.fmt(r.points[1].value), r.fmt(r.avg)]))));
    }

    // Pass/run tendencies
    const tRows = [];
    for (const [off, def, offTeam, defTeam] of [[a, h, g.away, g.home], [h, a, g.home, g.away]]) {
      if (off.pass_pct != null) tRows.push({ label: `${offTeam} offense: pass rate`, value: off.pass_pct, team: teamKey(offTeam, g), avg: L.pass_rate, valueText: fmtPct(off.pass_pct), tip: `${offTeam} drops back on ${fmtPct(off.pass_pct)} of neutral plays` });
      if (def.opp_pass_pct_allowed != null) tRows.push({ label: `${defTeam} defense: pass rate faced`, value: def.opp_pass_pct_allowed, team: teamKey(defTeam, g), avg: L.pass_rate, valueText: `${fmtPct(def.opp_pass_pct_allowed)}${def.opp_pass_pct_allowed_rank ? ` (#${def.opp_pass_pct_allowed_rank})` : ""}`, tip: `Offenses drop back on ${fmtPct(def.opp_pass_pct_allowed)} of neutral plays vs ${defTeam}` });
    }
    if (tRows.length)
      body.push(section("Pass/run tendencies", "Neutral situations (quarters 1-3, within 14 points). A defense that faces a lot of passes is a pass funnel; the thin line is the league average.", meterChart(tRows), d.insights.tendency,
        dataTable(["Row", "Pass rate"], tRows.map((r) => [r.label, r.valueText]))));

    // Positional matchups
    const posRows = (rows, offTeam, defTeam) =>
      rows.filter((r) => r.vs_avg != null).map((r) => ({
        label: `${r.position}s`,
        value: r.vs_avg,
        team: teamKey(offTeam, g),
        muted: r.vs_avg < 0,
        valueText: `${fmtSigned(r.vs_avg)}${r.rank ? ` (#${r.rank})` : ""}`,
        tip: `${defTeam} allow ${r.allowed} DK pts/game to ${r.position}s (league ${r.league_avg}); #${r.rank} most allowed`,
      }));
    const posCharts = [];
    const posTables = [];
    for (const [rows, offTeam, defTeam] of [[d.away_def_vs_pos, g.home, g.away], [d.home_def_vs_pos, g.away, g.home]]) {
      const pr = posRows(rows, offTeam, defTeam);
      if (!pr.length) continue;
      posCharts.push(el("div", { cls: "gd-facet" }, [el("h4", { text: `${offTeam} offense vs ${defTeam} defense` }), divergingChart(pr, 0.6, "League average")]));
      posTables.push(...rows.map((r) => [`${offTeam} ${r.position}s vs ${defTeam}`, r.allowed != null ? String(r.allowed) : "-", r.league_avg != null ? String(r.league_avg) : "-", fmtSigned(r.vs_avg), r.rank ? `#${r.rank}` : "-"]));
    }
    if (posCharts.length)
      body.push(section("Where to attack: DK points allowed by position", "Last 8 games vs the league average. Colored bars are positions this defense gives up more than average to; gray is below average. #1 = allows the most.",
        el("div", { cls: "gd-facets" }, posCharts), d.insights.positions,
        dataTable(["Matchup", "DK pts allowed/gm", "League avg", "vs avg", "Rank"], posTables)));

    // Usage
    const maxShare = Math.max(0.4, ...[...d.away_usage, ...d.home_usage].map((u) => Math.max(u.share_l3, u.share_l8 || 0)));
    const usageFacets = [];
    for (const [rows, team] of [[d.away_usage, g.away], [d.home_usage, g.home]]) {
      if (rows.length) usageFacets.push(el("div", { cls: "gd-facet" }, [el("h4", { text: `${team}` }), usageChart(rows, teamKey(team, g), maxShare)]));
    }
    if (usageFacets.length)
      body.push(section("Who gets the ball", "Share of team targets + carries. Bar = last 3 games; tick = last 8, so a bar past its tick is a growing role.",
        el("div", { cls: "gd-facets" }, usageFacets), d.insights.usage,
        dataTable(["Player", "Team", "Last 3", "Last 8"], [...d.away_usage.map((u) => [u.name, g.away, u]), ...d.home_usage.map((u) => [u.name, g.home, u])].map(([n, t, u]) => [n, t, fmtPct(u.share_l3), fmtPct(u.share_l8)]))));

    // Targets
    const targets = el("div", { cls: "gd-targets" });
    targets.innerHTML = `
      <div><h4>${escapeHtml(g.away)}</h4>${renderTargets(gb.away_top_players, 3)}</div>
      <div><h4>${escapeHtml(g.home)}</h4>${renderTargets(gb.home_top_players, 3)}</div>`;
    body.push(section("DFS targets", "Picked for this matchup: ceiling adjusted for the defense, implied total, funnels, tempo and usage, tilted toward what each offense does most. Value = best ceiling per $1k at $5,500 or less. Each team's DST is ranked against every DST this week.", targets, null));

    dialogBodyEl.replaceChildren(...body);
  }

  async function openGameDetail(gameId) {
    dialogTitleEl.textContent = "Loading matchup...";
    dialogBodyEl.replaceChildren(el("p", { cls: "breakdown-loading loading", text: "Loading advanced matchup stats..." }));
    if (!dialogEl.open) dialogEl.showModal();
    history.replaceState(null, "", `#game=${encodeURIComponent(gameId)}`);
    try {
      const d = await DFS.getJson(`/api/breakdown/game/${encodeURIComponent(gameId)}?season=${state.season}&week=${state.week}`, "detail");
      renderDetail(d);
    } catch (err) {
      if (DFS.isAbort(err)) return;
      dialogTitleEl.textContent = "Couldn't load this matchup";
      dialogBodyEl.replaceChildren(el("p", { cls: "empty-state", text: err.message }));
    }
  }

  function closeGameDetail() {
    if (dialogEl.open) dialogEl.close();
  }

  dialogEl.addEventListener("close", () => {
    tooltipEl.hidden = true;
    if (location.hash.startsWith("#game=")) history.replaceState(null, "", location.pathname + location.search);
  });
  dialogEl.addEventListener("click", (e) => {
    if (e.target === dialogEl) closeGameDetail(); // backdrop click
  });
  document.getElementById("gd-close").addEventListener("click", closeGameDetail);
  gamesEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".gd-open");
    if (btn) openGameDetail(btn.dataset.game);
  });

  // One shared tooltip for every [data-tip] mark: hover and keyboard focus alike.
  function showTip(target) {
    const tip = target.dataset.tip;
    if (!tip) return;
    tooltipEl.textContent = tip;
    tooltipEl.hidden = false;
    const r = target.getBoundingClientRect();
    const tw = tooltipEl.offsetWidth;
    const left = Math.max(8, Math.min(window.innerWidth - tw - 8, r.left + r.width / 2 - tw / 2));
    tooltipEl.style.left = left + "px";
    tooltipEl.style.top = Math.max(8, r.top - tooltipEl.offsetHeight - 8) + "px";
  }
  dialogBodyEl.addEventListener("pointerover", (e) => {
    const t = e.target.closest("[data-tip]");
    if (t) showTip(t);
  });
  dialogBodyEl.addEventListener("pointerout", (e) => {
    if (e.target.closest("[data-tip]")) tooltipEl.hidden = true;
  });
  dialogBodyEl.addEventListener("focusin", (e) => {
    const t = e.target.closest("[data-tip]");
    if (t) showTip(t);
  });
  dialogBodyEl.addEventListener("focusout", () => {
    tooltipEl.hidden = true;
  });
  dialogBodyEl.addEventListener("scroll", () => {
    tooltipEl.hidden = true;
  }, { passive: true });

  async function loadWeek() {
    state.season = DFS.season;
    state.week = DFS.week;
    weekLabelEl.textContent = state.week;

    gamesEl.innerHTML = "";
    emptyStateEl.hidden = true;
    emptyStateEl.textContent = "";

    const loading = document.createElement("p");
    loading.className = "breakdown-loading loading";
    loading.textContent = "Loading week breakdown...";
    gamesEl.appendChild(loading);

    try {
      const data = await DFS.getJson(`/api/breakdown?season=${state.season}&week=${state.week}`, "breakdown");
      weekLabelEl.textContent = data.week;
      gamesEl.innerHTML = "";
      if (data.games.length === 0) {
        emptyStateEl.hidden = false;
        emptyStateEl.textContent = "No games found for this week.";
        return;
      }
      for (const gb of data.games) {
        gamesEl.appendChild(renderGameCard(gb));
      }
      const m = location.hash.match(/^#game=(.+)$/);
      if (m && data.games.some((gb) => gb.game.game_id === decodeURIComponent(m[1]))) {
        openGameDetail(decodeURIComponent(m[1]));
      }
    } catch (err) {
      if (DFS.isAbort(err)) return;
      gamesEl.innerHTML = "";
      emptyStateEl.hidden = false;
      emptyStateEl.textContent = "Error loading week breakdown: " + err.message;
    }
  }

  DFS.onWeekChange(() => { closeGameDetail(); loadWeek(); });
  loadWeek();
})();
