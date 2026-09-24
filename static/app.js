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
    lineups: [],
    activeLineup: 0,
    optimal: null,
    injuryFilter: "all",
  };

  const L = window.DFSLineups;

  const scheduleStripEl = document.getElementById("schedule-strip");
  const oddsTbodyEl = document.getElementById("odds-tbody");
  const slateTabsEl = document.getElementById("slate-tabs");
  const unmatchedBannerEl = document.getElementById("unmatched-banner");
  const tbodyEl = document.getElementById("players-tbody");
  const emptyStateEl = document.getElementById("empty-state");
  const searchBoxEl = document.getElementById("search-box");
  const positionFiltersEl = document.getElementById("position-filters");
  const matchStatsEl = document.getElementById("match-stats");
  const lineupCardsEl = document.getElementById("lineup-cards");
  const lineupCountEl = document.getElementById("lineup-count");
  const lineupStatusEl = document.getElementById("lineup-status");
  const addLineupBtn = document.getElementById("add-lineup-btn");
  const lineupStickyEl = document.getElementById("lineup-sticky");
  const lineupStickySummaryEl = document.getElementById("lineup-sticky-summary");
  const lineupStickyStatusEl = document.getElementById("lineup-sticky-status");
  const optimalWrapEl = document.getElementById("optimal-wrap");
  const optimalStatusEl = document.getElementById("optimal-status");
  const optimalCardsEl = document.getElementById("optimal-cards");
  const injuryFilterEl = document.getElementById("injury-filter");
  const injuryHiddenCountEl = document.getElementById("injury-hidden-count");

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

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

  const INJURY_FILTER_KEY = "dfsriches:injuryFilter";
  const PLAYABLE_STATUSES = new Set(["Healthy", "Q"]);

  function passesInjuryFilter(p) {
    if (state.injuryFilter === "healthy") return p.injury === "Healthy";
    if (state.injuryFilter === "no_out") return PLAYABLE_STATUSES.has(p.injury);
    return true;
  }

  function getFilteredSortedPlayers() {
    let rows = state.players.filter(passesInjuryFilter);
    const hidden = state.players.length - rows.length;
    injuryHiddenCountEl.textContent = hidden ? `${hidden} hidden` : "";
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

    const active = state.lineups[state.activeLineup] || [];
    for (const p of rows) {
      const tr = document.createElement("tr");
      const slotHtml = p.roster_slot
        ? `<span class="slot-pill ${p.roster_slot}">${p.roster_slot}</span>`
        : "";
      const statusClass = p.injury === "Healthy" ? "status-healthy" : "status-injured";
      const valueClass = p.value_per_1k >= 3 ? "value-good" : "";
      const inActive = L.indexOfPlayer(active, p) !== -1;
      const exposure = state.lineups.filter((lu) => L.indexOfPlayer(lu, p) !== -1).length;
      tr.dataset.id = p.dk_draftable_id;
      tr.className = "player-row" + (inActive ? " in-lineup" : "");
      const btnLabel = `${inActive ? "Remove" : "Add"} ${p.name} ${inActive ? "from" : "to"} lineup ${state.activeLineup + 1}`;
      tr.innerHTML = `
        <td class="add-col">
          <button type="button" class="add-btn" aria-pressed="${inActive}" aria-label="${escapeHtml(btnLabel)}">${inActive ? "&minus;" : "+"}</button>
          ${exposure > 0 ? `<span class="exposure" title="In ${exposure} of ${state.lineups.length} lineups">${exposure}/${state.lineups.length}</span>` : ""}
        </td>
        <td>${slotHtml}</td>
        <td>${escapeHtml(p.name)}</td>
        <td>${escapeHtml(p.position)}</td>
        <td>${escapeHtml(p.team)}</td>
        <td>${escapeHtml(p.opponent)}</td>
        <td>${escapeHtml(p.game_info)}</td>
        <td class="num">${fmtSalary(p.salary)}</td>
        <td class="num">${p.proj_points.toFixed(1)}</td>
        <td class="num ceiling-cell"${p.ceiling_notes && p.ceiling_notes.length ? ` title="${escapeHtml(p.ceiling_notes.join("\n"))}"` : ""}>${p.ceiling != null ? p.ceiling.toFixed(1) : "-"}</td>
        <td class="num">${p.dk_fppg != null ? p.dk_fppg.toFixed(1) : "-"}</td>
        <td class="num">${p.trend_l3 != null ? p.trend_l3.toFixed(1) : "-"}</td>
        <td class="num">${p.trend_l6 != null ? p.trend_l6.toFixed(1) : "-"}</td>
        <td class="num">${p.trend_l9 != null ? p.trend_l9.toFixed(1) : "-"}</td>
        <td class="num">${p.sleeper_proj != null ? p.sleeper_proj.toFixed(1) : "-"}</td>
        <td class="num ${valueClass}">${p.value_per_1k.toFixed(2)}</td>
        <td class="${statusClass}">${escapeHtml(p.injury || "")}</td>
      `;
      tbodyEl.appendChild(tr);
    }

    document.querySelectorAll("#players-table thead th[data-key]").forEach((th) => {
      const isSorted = th.dataset.key === state.sortKey;
      th.classList.toggle("sorted", isSorted);
      th.setAttribute("aria-sort", isSorted ? (state.sortDir === "asc" ? "ascending" : "descending") : "none");
    });
    updateScrollShadow(tbodyEl.closest(".table-scroll"));
  }

  function activeSlateType() {
    const slate = state.slates.find((s) => s.slate_id === state.activeSlateId);
    return slate ? slate.slate_type : "classic";
  }

  function lineupStorageKey() {
    return `dfsriches:lineups:${state.season}:${state.week}:${state.activeSlateId}`;
  }

  function saveLineups() {
    const payload = {
      active: state.activeLineup,
      lineups: state.lineups.map((lu) => lu.map((p) => (p ? p.dk_draftable_id : null))),
    };
    try {
      localStorage.setItem(lineupStorageKey(), JSON.stringify(payload));
    } catch (_e) {
      // storage unavailable (private mode, blocked): lineups just won't persist
    }
  }

  function loadLineups() {
    const slateType = activeSlateType();
    const byId = new Map(state.players.map((p) => [p.dk_draftable_id, p]));
    let saved = null;
    try {
      saved = JSON.parse(localStorage.getItem(lineupStorageKey()) || "null");
    } catch (_e) {
      saved = null;
    }
    const size = L.emptyLineup(slateType).length;
    const lineups = saved && Array.isArray(saved.lineups)
      ? saved.lineups
          .slice(0, L.MAX_LINEUPS)
          .filter((ids) => Array.isArray(ids) && ids.length === size)
          .map((ids) => ids.map((id) => byId.get(id) || null))
      : [];
    state.lineups = lineups.length ? lineups : [L.emptyLineup(slateType)];
    const active = saved ? Number(saved.active) : 0;
    state.activeLineup = active >= 0 && active < state.lineups.length ? active : 0;
  }

  function setLineupStatus(msg, isError) {
    lineupStatusEl.textContent = msg || "";
    lineupStatusEl.classList.toggle("error", Boolean(isError));
    lineupStickyStatusEl.textContent = msg || "";
    lineupStickyStatusEl.classList.toggle("error", Boolean(isError));
  }

  function fmtPts(n) {
    return n.toFixed(1);
  }

  function renderLineups() {
    const slateType = activeSlateType();
    const defs = L.template(slateType);
    const summaries = state.lineups.map((lu) => L.summarize(lu, slateType));
    const withPlayers = summaries.map((s, i) => [s, i]).filter(([s]) => s.filled > 0);
    const bestIdx = withPlayers.length > 1
      ? withPlayers.reduce((best, cur) => (cur[0].proj > best[0].proj ? cur : best))[1]
      : -1;

    lineupCountEl.textContent = `(${state.lineups.length}/${L.MAX_LINEUPS})`;
    addLineupBtn.disabled = state.lineups.length >= L.MAX_LINEUPS || state.players.length === 0;

    lineupCardsEl.innerHTML = "";
    state.lineups.forEach((lu, i) => {
      const s = summaries[i];
      const isActive = i === state.activeLineup;
      const card = document.createElement("article");
      card.className = "lineup-card" + (isActive ? " active" : "") + (i === bestIdx ? " best" : "");
      card.dataset.index = i;

      const slotsHtml = defs
        .map((def, si) => {
          const p = lu[si];
          if (!p) {
            return `<li class="lineup-slot empty"><span class="ls-label">${def.label}</span><span class="ls-name">&mdash;</span></li>`;
          }
          return `
            <li class="lineup-slot">
              <span class="ls-label">${def.label}</span>
              <span class="ls-name">${escapeHtml(p.name)} <span class="ls-team">${escapeHtml(p.position)} &middot; ${escapeHtml(p.team)}</span></span>
              <span class="ls-salary">${fmtSalary(p.salary)}</span>
              <span class="ls-proj">${fmtPts(p.proj_points || 0)}</span>
              <button type="button" class="ls-remove" data-slot="${si}" aria-label="Remove ${escapeHtml(p.name)} from lineup ${i + 1}">&times;</button>
            </li>`;
        })
        .join("");

      const remainingCls = s.remaining < 0 ? "over" : "";
      const sleeperTxt = s.sleeperCount ? `${fmtPts(s.sleeperProj)}${s.sleeperCount < s.filled ? ` <span class="lt-note">(${s.sleeperCount}/${s.filled})</span>` : ""}` : "-";
      card.innerHTML = `
        <header class="lineup-card-header">
          <button type="button" class="lineup-select" aria-pressed="${isActive}">Lineup ${i + 1}</button>
          ${i === bestIdx ? '<span class="lineup-best">Top proj</span>' : ""}
          <span class="lineup-badge ${s.valid ? "valid" : "invalid"}">${s.valid ? "Valid" : `${s.filled}/${s.total}`}</span>
          <button type="button" class="lineup-clear" aria-label="Clear lineup ${i + 1}">Clear</button>
          <button type="button" class="lineup-delete" aria-label="Delete lineup ${i + 1}">&times;</button>
        </header>
        <ol class="lineup-slots">${slotsHtml}</ol>
        <dl class="lineup-totals">
          <div><dt>Salary</dt><dd>${fmtSalary(s.salary)}</dd></div>
          <div><dt>Remaining</dt><dd class="${remainingCls}">${s.remaining < 0 ? "-" : ""}${fmtSalary(Math.abs(s.remaining))}</dd></div>
          <div><dt>Avg/open slot</dt><dd>${s.avgRemaining != null ? fmtSalary(Math.max(0, s.avgRemaining)) : "-"}</dd></div>
          <div><dt>Proj</dt><dd class="lt-proj">${fmtPts(s.proj)}</dd></div>
          <div><dt>Ceiling</dt><dd class="lt-ceiling">${fmtPts(s.ceiling)}</dd></div>
          <div><dt>Sleeper Proj</dt><dd>${sleeperTxt}</dd></div>
        </dl>
        ${s.errors.length && s.filled > 0 ? `<ul class="lineup-errors">${s.errors.map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul>` : ""}
      `;
      lineupCardsEl.appendChild(card);
    });
    updateScrollShadow(lineupCardsEl.closest(".table-scroll"));

    const cur = summaries[state.activeLineup];
    lineupStickyEl.hidden = !cur || state.players.length === 0;
    if (cur) {
      lineupStickySummaryEl.innerHTML =
        `<strong>Lineup ${state.activeLineup + 1}</strong> ${cur.filled}/${cur.total} &middot; ` +
        `<span class="${cur.remaining < 0 ? "over" : ""}">${cur.remaining < 0 ? "-" : ""}${fmtSalary(Math.abs(cur.remaining))} left</span> &middot; ` +
        `Proj <span class="lt-proj">${fmtPts(cur.proj)}</span> &middot; Ceiling <span class="lt-ceiling">${fmtPts(cur.ceiling)}</span>`;
    }
  }

  function refreshLineupViews() {
    saveLineups();
    renderLineups();
    renderTable();
  }

  function togglePlayer(player) {
    const slateType = activeSlateType();
    const lu = state.lineups[state.activeLineup];
    const idx = L.indexOfPlayer(lu, player);
    if (idx !== -1) {
      state.lineups[state.activeLineup] = L.removeAt(lu, idx);
      setLineupStatus(`Removed ${player.name} from Lineup ${state.activeLineup + 1}.`);
    } else {
      const res = L.addPlayer(lu, slateType, player);
      if (!res.ok) {
        setLineupStatus(res.reason, true);
        return;
      }
      state.lineups[state.activeLineup] = res.slots;
      const label = L.template(slateType)[res.index].label;
      setLineupStatus(`Added ${player.name} to Lineup ${state.activeLineup + 1} (${label}).`);
    }
    refreshLineupViews();
  }

  function selectLineup(i) {
    if (i === state.activeLineup) return;
    state.activeLineup = i;
    setLineupStatus(`Now editing Lineup ${i + 1} -- click players below to add them.`);
    refreshLineupViews();
  }

  function fmtEt(iso) {
    return new Date(iso).toLocaleString("en-US", {
      timeZone: "America/New_York", weekday: "short", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit",
    }) + " ET";
  }

  function optimalStatusText(opt) {
    if (opt.status === "live") return `-- live, recalculated until kickoff (last change saved ${fmtEt(opt.saved_at)})`;
    if (opt.status === "saved") return `-- saved before kickoff, ${fmtEt(opt.saved_at)}; actual scores are added once every game is final`;
    if (opt.status === "final") {
      const pre = opt.saved_at ? `saved before kickoff ${fmtEt(opt.saved_at)}` : "no pre-kickoff lineups were saved for this slate";
      return `-- final: ${pre}; actual scores added ${fmtEt(opt.results_at)}`;
    }
    return "-- none saved: this slate started before optimal lineups were being recorded.";
  }

  function optimalCardHtml(lu, i, isHindsight) {
    const hasActual = lu.actual != null;
    const rows = lu.players
      .map((p) => {
        const main = isHindsight ? p.actual : p[lu.metric];
        const actual = !isHindsight && p.actual != null
          ? `<span class="ls-actual" title="Actual DK points">${fmtPts(p.actual)}</span>` : "";
        return `
          <li class="lineup-slot optimal-slot${actual ? " with-actual" : ""}">
            <span class="ls-label">${escapeHtml(p.slot)}</span>
            <span class="ls-name">${escapeHtml(p.name)} <span class="ls-team">${escapeHtml(p.position)} &middot; ${escapeHtml(p.team)}</span></span>
            <span class="ls-salary">${fmtSalary(p.salary)}</span>
            <span class="ls-proj">${fmtPts(main || 0)}</span>
            ${actual}
          </li>`;
      })
      .join("");
    const totals = isHindsight
      ? `<div><dt>Salary</dt><dd>${fmtSalary(lu.salary)}</dd></div>
         <div><dt>Actual</dt><dd class="lt-actual">${fmtPts(lu.actual)}</dd></div>`
      : `<div><dt>Salary</dt><dd>${fmtSalary(lu.salary)}</dd></div>
         <div><dt>Remaining</dt><dd>${fmtSalary(L.SALARY_CAP - lu.salary)}</dd></div>
         <div><dt>Proj</dt><dd class="lt-proj">${fmtPts(lu.proj_points)}</dd></div>
         <div><dt>Ceiling</dt><dd class="lt-ceiling">${fmtPts(lu.ceiling)}</dd></div>
         ${hasActual ? `<div><dt>Actual</dt><dd class="lt-actual">${fmtPts(lu.actual)}</dd></div>` : ""}`;
    return `
      <header class="lineup-card-header">
        <span class="optimal-title">${escapeHtml(lu.label)}</span>
        ${isHindsight ? "" : `<button type="button" class="optimal-copy" data-index="${i}">Copy to my lineups</button>`}
      </header>
      ${isHindsight ? '<p class="optimal-note">Highest-scoring lineup possible under the salary cap, using actual points.</p>' : ""}
      <ol class="lineup-slots">${rows}</ol>
      <dl class="lineup-totals">${totals}</dl>
    `;
  }

  function renderOptimal() {
    const opt = state.optimal;
    optimalCardsEl.innerHTML = "";
    const cards = opt ? opt.lineups.map((lu, i) => [lu, i, false]) : [];
    if (opt && opt.hindsight) cards.push([opt.hindsight, -1, true]);
    optimalWrapEl.hidden = !opt || (!cards.length && opt.status !== "none");
    if (!opt) return;
    optimalStatusEl.textContent = optimalStatusText(opt);

    for (const [lu, i, isHindsight] of cards) {
      const card = document.createElement("article");
      card.className = "lineup-card optimal-card" + (isHindsight ? " hindsight-card" : "");
      card.innerHTML = optimalCardHtml(lu, i, isHindsight);
      optimalCardsEl.appendChild(card);
    }
    updateScrollShadow(optimalCardsEl.closest(".table-scroll"));
  }

  async function loadOptimal(slateId) {
    state.optimal = null;
    renderOptimal();
    const requested = `${state.season}|${state.week}|${slateId}`;
    const isCurrent = () => requested === `${state.season}|${state.week}|${state.activeSlateId}`;
    let data = null;
    try {
      data = await fetchJson(
        `/api/slates/${encodeURIComponent(slateId)}/optimal?season=${state.season}&week=${state.week}`
      );
    } catch (_err) {
      data = null;
    }
    if (!isCurrent()) return;
    state.optimal = data;
    renderOptimal();
  }

  optimalCardsEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".optimal-copy");
    if (!btn || !state.optimal) return;
    const lu = state.optimal.lineups[Number(btn.dataset.index)];
    const activeIsEmpty = (state.lineups[state.activeLineup] || []).every((p) => !p);
    if (!activeIsEmpty && state.lineups.length >= L.MAX_LINEUPS) {
      setLineupStatus(`You already have ${L.MAX_LINEUPS} lineups -- delete one to copy ${lu.label}.`, true);
      return;
    }
    const byId = new Map(state.players.map((p) => [p.dk_draftable_id, p]));
    const slateType = activeSlateType();
    let slots = L.emptyLineup(slateType);
    const missing = [];
    for (const saved of lu.players) {
      const p = byId.get(saved.dk_draftable_id);
      const res = p ? L.addPlayer(slots, slateType, p) : { ok: false };
      if (res.ok) slots = res.slots;
      else missing.push(saved.name);
    }
    if (activeIsEmpty && state.lineups.length) {
      state.lineups[state.activeLineup] = slots;
    } else {
      state.lineups.push(slots);
      state.activeLineup = state.lineups.length - 1;
    }
    const target = state.activeLineup + 1;
    setLineupStatus(
      missing.length
        ? `Copied ${lu.label} to Lineup ${target}; not in today's player pool: ${missing.join(", ")}.`
        : `Copied ${lu.label} to Lineup ${target} -- edit it like any other lineup.`,
      missing.length > 0
    );
    refreshLineupViews();
  });

  addLineupBtn.addEventListener("click", () => {
    if (state.lineups.length >= L.MAX_LINEUPS) return;
    state.lineups.push(L.emptyLineup(activeSlateType()));
    state.activeLineup = state.lineups.length - 1;
    setLineupStatus(`Created Lineup ${state.lineups.length} -- click players below to add them.`);
    refreshLineupViews();
  });

  lineupCardsEl.addEventListener("click", (e) => {
    const card = e.target.closest(".lineup-card");
    if (!card) return;
    const i = Number(card.dataset.index);

    if (e.target.closest(".ls-remove")) {
      const si = Number(e.target.closest(".ls-remove").dataset.slot);
      const p = state.lineups[i][si];
      state.lineups[i] = L.removeAt(state.lineups[i], si);
      setLineupStatus(p ? `Removed ${p.name} from Lineup ${i + 1}.` : "");
      refreshLineupViews();
      return;
    }
    if (e.target.closest(".lineup-clear")) {
      state.lineups[i] = L.emptyLineup(activeSlateType());
      setLineupStatus(`Cleared Lineup ${i + 1}.`);
      refreshLineupViews();
      return;
    }
    if (e.target.closest(".lineup-delete")) {
      if (state.lineups.length === 1) {
        state.lineups[0] = L.emptyLineup(activeSlateType());
      } else {
        state.lineups.splice(i, 1);
        if (state.activeLineup >= state.lineups.length || state.activeLineup > i) {
          state.activeLineup = Math.max(0, state.activeLineup - 1);
        }
      }
      setLineupStatus(`Deleted Lineup ${i + 1}.`);
      refreshLineupViews();
      return;
    }
    selectLineup(i);
  });

  tbodyEl.addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (!tr) return;
    const player = state.players.find((p) => String(p.dk_draftable_id) === tr.dataset.id);
    if (player) togglePlayer(player);
  });

  async function selectSlate(slateId) {
    state.activeSlateId = slateId;
    state.activePositions.clear();
    state.optimal = null;
    renderOptimal();
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
      loadLineups();
      setLineupStatus(
        state.players.length
          ? `Editing Lineup ${state.activeLineup + 1} -- click players below to add them.`
          : "Lineups open up once DraftKings posts salaries for this slate."
      );
      renderLineups();
      renderUnmatchedBanner();
      renderPositionFilters();
      renderTable();
      loadOptimal(slateId);
    } catch (err) {
      state.players = [];
      state.lineups = [];
      renderLineups();
      setLineupStatus("");
      matchStatsEl.textContent = "";
      tbodyEl.innerHTML = "";
      emptyStateEl.hidden = false;
      emptyStateEl.textContent = "Error loading slate: " + err.message;
    }
  }

  async function loadWeek() {
    state.season = Number(document.getElementById("season-input").value);
    state.week = Number(document.getElementById("week-input").value);
    state.optimal = null;
    renderOptimal();

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
  try {
    const saved = localStorage.getItem(INJURY_FILTER_KEY);
    if (saved && [...injuryFilterEl.options].some((o) => o.value === saved)) state.injuryFilter = saved;
  } catch (_e) {
    // storage unavailable: default to showing all players
  }
  injuryFilterEl.value = state.injuryFilter;
  injuryFilterEl.addEventListener("change", (e) => {
    state.injuryFilter = e.target.value;
    try {
      localStorage.setItem(INJURY_FILTER_KEY, state.injuryFilter);
    } catch (_e) {
      // storage unavailable: the choice just won't persist
    }
    renderTable();
  });
  document.querySelectorAll("#players-table thead th[data-key]").forEach((th) => {
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
