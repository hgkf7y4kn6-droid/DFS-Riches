(function () {
  "use strict";

  const state = {
    season: Number(document.getElementById("season-input").value),
    week: Number(document.getElementById("week-input").value),
    slates: [],
    activeSlateId: null,
    players: [],
    unmatched: [],
    sortKey: "salary",
    sortDir: "desc",
    search: "",
    activePositions: new Set(),
  };

  const scheduleStripEl = document.getElementById("schedule-strip");
  const oddsTbodyEl = document.getElementById("odds-tbody");
  const slateTabsEl = document.getElementById("slate-tabs");
  const unmatchedBannerEl = document.getElementById("unmatched-banner");
  const tbodyEl = document.getElementById("players-tbody");
  const emptyStateEl = document.getElementById("empty-state");
  const searchBoxEl = document.getElementById("search-box");
  const positionFiltersEl = document.getElementById("position-filters");
  const matchStatsEl = document.getElementById("match-stats");

  function updateScrollShadow(el) {
    if (!el) return;
    const canScroll = el.scrollWidth > el.clientWidth + 1;
    el.classList.toggle("can-scroll-left", canScroll && el.scrollLeft > 1);
    el.classList.toggle("can-scroll-right", canScroll && el.scrollLeft < el.scrollWidth - el.clientWidth - 1);
  }

  function initScrollShadows() {
    document.querySelectorAll(".table-scroll").forEach((el) => {
      updateScrollShadow(el);
      el.addEventListener("scroll", () => updateScrollShadow(el), { passive: true });
    });
    window.addEventListener("resize", () => {
      document.querySelectorAll(".table-scroll").forEach(updateScrollShadow);
    });
  }

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

  function renderSchedule(schedule) {
    scheduleStripEl.innerHTML = "";
    for (const g of schedule.games) {
      const chip = document.createElement("div");
      chip.className = "game-chip" + (g.isolated ? " isolated" : "");
      chip.innerHTML = `
        <div class="matchup">${g.away} @ ${g.home}</div>
        <div class="meta">${g.kickoff_et}${g.network ? " · " + g.network : ""}</div>
        ${g.isolated ? `<div class="badge">${g.day_part.replace("_", " ")}</div>` : ""}
      `;
      scheduleStripEl.appendChild(chip);
    }
    updateScrollShadow(scheduleStripEl);
  }

  function fmtSigned(n, decimals) {
    if (n == null) return "-";
    const s = n.toFixed(decimals == null ? 1 : decimals);
    return n > 0 ? "+" + s : s;
  }

  function fmtTrendLine(awayTrend, homeTrend, opts) {
    if (!awayTrend && !homeTrend) return "";
    const signed = opts && opts.signed;
    const decimals = opts && opts.decimals != null ? opts.decimals : 1;
    const fmtVal = (v) => {
      if (v == null) return "-";
      const s = v.toFixed(decimals);
      return signed && v > 0 ? "+" + s : s;
    };
    const a = awayTrend || {};
    const h = homeTrend || {};
    return `L3 ${fmtVal(a.l3)}/${fmtVal(h.l3)} &nbsp; L6 ${fmtVal(a.l6)}/${fmtVal(h.l6)} &nbsp; L9 ${fmtVal(a.l9)}/${fmtVal(h.l9)}`;
  }

  function fmtSpreadPair(g) {
    const c = g.context;
    if (!c || c.away_spread == null) return "-";
    const main = `${g.away} ${fmtSigned(c.away_spread)} / ${g.home} ${fmtSigned(c.home_spread)}`;
    const trend = fmtTrendLine(c.away_spread_trend, c.home_spread_trend, { signed: true });
    return `${main}<div class="cell-sub">${trend}</div>`;
  }

  function fmtImpliedPair(g) {
    const c = g.context;
    if (!c || c.away_implied_total == null) return "-";
    const main = `${c.away_implied_total.toFixed(1)} / ${c.home_implied_total.toFixed(1)}`;
    const trend = fmtTrendLine(c.away_implied_total_trend, c.home_implied_total_trend);
    return `${main}<div class="cell-sub">${trend}</div>`;
  }

  function fmtTotalCell(g) {
    const c = g.context;
    if (!c || c.total_line == null) return "-";
    const trend = fmtTrendLine(c.away_total_trend, c.home_total_trend);
    return `${c.total_line.toFixed(1)}<div class="cell-sub">${trend}</div>`;
  }

  function fmtFinalPair(g) {
    const c = g.context;
    if (!c || !c.is_final) return '<span class="pending">not final</span>';
    return `${c.away_score} / ${c.home_score}`;
  }

  function fmtAtsResult(g) {
    const c = g.context;
    if (!c || !c.is_final || c.spread_result == null) return '<span class="pending">-</span>';
    if (c.spread_result === 0) return '<span class="push">Push</span>';
    const coveringTeam = c.spread_result > 0 ? g.home : g.away;
    const margin = Math.abs(c.spread_result).toFixed(1);
    return `<span class="beat">${coveringTeam} covered +${margin}</span>`;
  }

  function fmtTotalResult(g) {
    const c = g.context;
    if (!c || !c.is_final || c.total_result == null) return '<span class="pending">-</span>';
    if (c.total_result === 0) return '<span class="push">Push</span>';
    const cls = c.total_result > 0 ? "beat" : "missed";
    const label = c.total_result > 0 ? "Over" : "Under";
    return `<span class="${cls}">${label} ${fmtSigned(c.total_result)}</span>`;
  }

  function fmtPaceCell(g) {
    const c = g.context;
    if (!c) return '<span class="pending">-</span>';
    const parts = [];
    for (const [label, pace] of [[g.away, c.away_pace], [g.home, c.home_pace]]) {
      if (!c.is_final || !pace || pace.delta == null) {
        parts.push(`${label} -`);
        continue;
      }
      const cls = pace.delta > 0 ? "pace-pos" : pace.delta < 0 ? "pace-neg" : "";
      const title = `${label}: ${pace.actual_plays} plays vs ${pace.baseline_plays} baseline`;
      parts.push(`<span class="${cls}" title="${title}">${label} ${fmtSigned(pace.delta, 1)}</span>`);
    }
    const main = parts.join(" &nbsp;/&nbsp; ");
    const trend = fmtTrendLine(c.away_pace && c.away_pace.trend, c.home_pace && c.home_pace.trend, { decimals: 0 });
    return `${main}<div class="cell-sub">${trend}</div>`;
  }

  function renderOddsTable(schedule) {
    oddsTbodyEl.innerHTML = "";
    for (const g of schedule.games) {
      const tr = document.createElement("tr");
      tr.className = g.isolated ? "isolated-row" : "";
      tr.innerHTML = `
        <td>${g.away} @ ${g.home}</td>
        <td>${g.kickoff_et}</td>
        <td class="num">${fmtSpreadPair(g)}</td>
        <td class="num">${fmtTotalCell(g)}</td>
        <td class="num">${fmtImpliedPair(g)}</td>
        <td class="num">${fmtFinalPair(g)}</td>
        <td>${fmtAtsResult(g)}</td>
        <td>${fmtTotalResult(g)}</td>
        <td class="num">${fmtPaceCell(g)}</td>
      `;
      oddsTbodyEl.appendChild(tr);
    }
    updateScrollShadow(oddsTbodyEl.closest(".table-scroll"));
  }

  function renderTabs() {
    slateTabsEl.innerHTML = "";
    for (const slate of state.slates) {
      const tab = document.createElement("button");
      const srcTag = slate.source === "override" ? " (cached)" : slate.source === "unavailable" ? " (unavailable)" : "";
      tab.className =
        "slate-tab" +
        (slate.slate_id === state.activeSlateId ? " active" : "") +
        (!slate.available ? " unavailable" : "");
      tab.innerHTML = `${slate.label}<span class="src-tag">${srcTag}</span>`;
      tab.disabled = !slate.available;
      tab.setAttribute("aria-pressed", String(slate.slate_id === state.activeSlateId));
      tab.addEventListener("click", () => selectSlate(slate.slate_id));
      slateTabsEl.appendChild(tab);
    }
  }

  const POSITION_ORDER = ["QB", "RB", "WR", "TE", "DST"];

  function renderPositionFilters() {
    const present = new Set(state.players.map((p) => p.position));
    const positions = POSITION_ORDER.filter((pos) => present.has(pos));
    for (const pos of present) {
      if (!positions.includes(pos)) positions.push(pos); // any unexpected position still shows, at the end
    }
    positionFiltersEl.innerHTML = "";
    const allBtn = document.createElement("button");
    allBtn.textContent = "ALL";
    allBtn.className = state.activePositions.size === 0 ? "active" : "";
    allBtn.setAttribute("aria-pressed", String(state.activePositions.size === 0));
    allBtn.addEventListener("click", () => {
      state.activePositions.clear();
      renderPositionFilters();
      renderTable();
    });
    positionFiltersEl.appendChild(allBtn);

    for (const pos of positions) {
      const btn = document.createElement("button");
      btn.textContent = pos;
      btn.className = state.activePositions.has(pos) ? "active" : "";
      btn.setAttribute("aria-pressed", String(state.activePositions.has(pos)));
      btn.addEventListener("click", () => {
        if (state.activePositions.has(pos)) {
          state.activePositions.delete(pos);
        } else {
          state.activePositions.add(pos);
        }
        renderPositionFilters();
        renderTable();
      });
      positionFiltersEl.appendChild(btn);
    }
  }

  function renderUnmatchedBanner() {
    if (state.unmatched.length === 0) {
      unmatchedBannerEl.hidden = true;
      unmatchedBannerEl.textContent = "";
      return;
    }
    unmatchedBannerEl.hidden = false;
    unmatchedBannerEl.textContent =
      `${state.unmatched.length} DraftKings player(s) could not be matched to a Sleeper projection ` +
      `(shown with 0.0 proj): ${state.unmatched.join(", ")}`;
  }

  function getFilteredSortedPlayers() {
    let rows = state.players;
    if (state.activePositions.size > 0) {
      rows = rows.filter((p) => state.activePositions.has(p.position));
    }
    if (state.search.trim()) {
      const q = state.search.trim().toLowerCase();
      rows = rows.filter(
        (p) => p.name.toLowerCase().includes(q) || p.team.toLowerCase().includes(q) || p.opponent.toLowerCase().includes(q)
      );
    }
    const key = state.sortKey;
    const dir = state.sortDir === "asc" ? 1 : -1;
    rows = rows.slice().sort((a, b) => {
      let av = a[key];
      let bv = b[key];
      if (typeof av === "string") av = av.toLowerCase();
      if (typeof bv === "string") bv = bv.toLowerCase();
      if (av == null) av = -Infinity;
      if (bv == null) bv = -Infinity;
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
    return rows;
  }

  function renderTable() {
    const rows = getFilteredSortedPlayers();
    tbodyEl.innerHTML = "";
    emptyStateEl.hidden = rows.length > 0;
    if (rows.length === 0) {
      emptyStateEl.textContent = state.players.length === 0
        ? "No salary data available for this slate yet."
        : "No players match your filters.";
    }

    for (const p of rows) {
      const tr = document.createElement("tr");
      const slotHtml = p.roster_slot
        ? `<span class="slot-pill ${p.roster_slot}">${p.roster_slot}</span>`
        : "";
      const statusClass = p.injury === "Healthy" ? "status-healthy" : "status-injured";
      const valueClass = p.value_per_1k >= 3 ? "value-good" : "";
      tr.innerHTML = `
        <td>${slotHtml}</td>
        <td>${p.name}</td>
        <td>${p.position}</td>
        <td>${p.team}</td>
        <td>${p.opponent}</td>
        <td>${p.game_info}</td>
        <td class="num">${fmtSalary(p.salary)}</td>
        <td class="num">${p.proj_points.toFixed(1)}</td>
        <td class="num">${p.dk_fppg != null ? p.dk_fppg.toFixed(1) : "-"}</td>
        <td class="num">${p.trend_l3 != null ? p.trend_l3.toFixed(1) : "-"}</td>
        <td class="num">${p.trend_l6 != null ? p.trend_l6.toFixed(1) : "-"}</td>
        <td class="num">${p.trend_l9 != null ? p.trend_l9.toFixed(1) : "-"}</td>
        <td class="num">${p.sleeper_proj != null ? p.sleeper_proj.toFixed(1) : "-"}</td>
        <td class="num ${valueClass}">${p.value_per_1k.toFixed(2)}</td>
        <td class="${statusClass}">${p.injury || ""}</td>
      `;
      tbodyEl.appendChild(tr);
    }

    document.querySelectorAll("#players-table thead th").forEach((th) => {
      const isSorted = th.dataset.key === state.sortKey;
      th.classList.toggle("sorted", isSorted);
      th.setAttribute("aria-sort", isSorted ? (state.sortDir === "asc" ? "ascending" : "descending") : "none");
    });
    updateScrollShadow(tbodyEl.closest(".table-scroll"));
  }

  async function selectSlate(slateId) {
    state.activeSlateId = slateId;
    state.activePositions.clear();
    renderTabs();
    tbodyEl.innerHTML = "";
    matchStatsEl.textContent = "Loading...";

    try {
      const data = await fetchJson(
        `/api/slates/${encodeURIComponent(slateId)}/players?season=${state.season}&week=${state.week}`
      );
      state.players = data.players;
      state.unmatched = data.unmatched_dk_names;
      matchStatsEl.textContent = `${data.match_count}/${data.total_count} players matched to Sleeper projections`;
      renderUnmatchedBanner();
      renderPositionFilters();
      renderTable();
    } catch (err) {
      matchStatsEl.textContent = "";
      tbodyEl.innerHTML = "";
      emptyStateEl.hidden = false;
      emptyStateEl.textContent = "Error loading slate: " + err.message;
    }
  }

  async function loadWeek() {
    state.season = Number(document.getElementById("season-input").value);
    state.week = Number(document.getElementById("week-input").value);

    scheduleStripEl.innerHTML = "";
    oddsTbodyEl.innerHTML = "";
    slateTabsEl.innerHTML = "";
    tbodyEl.innerHTML = "";
    unmatchedBannerEl.hidden = true;
    matchStatsEl.textContent = "Loading schedule...";

    try {
      const weekData = await fetchJson(`/api/week?season=${state.season}&week=${state.week}`);
      const schedule = weekData.schedule;
      renderSchedule(schedule);
      renderOddsTable(schedule);

      const slateList = weekData.slates;
      state.slates = slateList;
      const firstAvailable = slateList.find((s) => s.available) || slateList[0];
      state.activeSlateId = firstAvailable ? firstAvailable.slate_id : null;
      renderTabs();

      if (state.activeSlateId) {
        await selectSlate(state.activeSlateId);
      } else {
        matchStatsEl.textContent = "";
      }
    } catch (err) {
      matchStatsEl.textContent = "";
      emptyStateEl.hidden = false;
      emptyStateEl.textContent = "Error loading week: " + err.message;
    }
  }

  document.getElementById("load-week-btn").addEventListener("click", loadWeek);
  searchBoxEl.addEventListener("input", (e) => {
    state.search = e.target.value;
    renderTable();
  });
  document.querySelectorAll("#players-table thead th").forEach((th) => {
    const sortByThisColumn = () => {
      const key = th.dataset.key;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = "desc";
      }
      renderTable();
    };
    th.tabIndex = 0;
    th.setAttribute("role", "button");
    th.addEventListener("click", sortByThisColumn);
    th.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        sortByThisColumn();
      }
    });
  });

  initScrollShadows();
  loadWeek();
})();
