(function () {
  "use strict";

  const gamesEl = document.getElementById("breakdown-games");
  const emptyStateEl = document.getElementById("breakdown-empty-state");
  const weekLabelEl = document.getElementById("breakdown-week-label");

  async function fetchJson(url) {
    const res = await fetch(url);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed: ${res.status}`);
    }
    return res.json();
  }

  function fmtSalary(n) {
    return "$" + n.toLocaleString("en-US");
  }

  function fmtNum(v, decimals) {
    if (v == null) return "-";
    return v.toFixed(decimals == null ? 1 : decimals);
  }

  function fmtPct(v) {
    if (v == null) return "-";
    return Math.round(v * 100) + "%";
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

  function renderTopPlayers(players) {
    if (!players || players.length === 0) {
      return '<span class="no-players">No salary data posted yet</span>';
    }
    return players
      .map(
        (p) =>
          `<span class="top-player"><span class="tp-pos">${p.position}</span> ${p.name} ` +
          `<span class="tp-salary">${fmtSalary(p.salary)}</span>` +
          (p.trend_l3 != null ? ` <span class="tp-trend">L3 ${p.trend_l3.toFixed(1)}</span>` : "") +
          `</span>`
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
        <div class="matchup">${g.away} @ ${g.home}</div>
        <div class="meta">${g.kickoff_et}${g.network ? " &middot; " + g.network : ""}</div>
      </header>

      <div class="table-scroll">
        <table class="breakdown-stat-table">
          <thead>
            <tr>
              <th scope="col" title="Last 8 games; tempo and pass rates are season-to-date once a team has 2+ games">Metric</th>
              <th scope="col" class="num">${g.away}</th>
              <th scope="col" class="num">${g.home}</th>
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
        ${gb.takeaways.map((t) => `<li>${t}</li>`).join("")}
      </ul>

      <div class="breakdown-top-players">
        <div class="tp-team">
          <span class="tp-team-label">${g.away} to watch</span>
          <div class="tp-list">${renderTopPlayers(gb.away_top_players)}</div>
        </div>
        <div class="tp-team">
          <span class="tp-team-label">${g.home} to watch</span>
          <div class="tp-list">${renderTopPlayers(gb.home_top_players)}</div>
        </div>
      </div>
    `;
    return card;
  }

  async function loadWeek() {
    const season = Number(document.getElementById("season-input").value);
    const week = Number(document.getElementById("week-input").value);
    weekLabelEl.textContent = week;

    gamesEl.innerHTML = "";
    emptyStateEl.hidden = true;
    emptyStateEl.textContent = "";

    const loading = document.createElement("p");
    loading.className = "breakdown-loading";
    loading.textContent = "Loading week breakdown...";
    gamesEl.appendChild(loading);

    try {
      const data = await fetchJson(`/api/breakdown?season=${season}&week=${week}`);
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
    } catch (err) {
      gamesEl.innerHTML = "";
      emptyStateEl.hidden = false;
      emptyStateEl.textContent = "Error loading week breakdown: " + err.message;
    }
  }

  document.getElementById("load-week-btn").addEventListener("click", loadWeek);
  loadWeek();
})();
