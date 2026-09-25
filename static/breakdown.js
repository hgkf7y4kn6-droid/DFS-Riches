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
          <div class="meta">${escapeHtml(g.kickoff_et)}${g.network ? " &middot; " + escapeHtml(g.network) : ""}</div>
        </div>
        <button type="button" class="gd-open" data-game="${escapeHtml(g.game_id)}">Advanced matchup &rarr;</button>
      </header>

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
