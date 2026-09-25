(function () {
  "use strict";

  const panelEl = document.getElementById("dm-panel");
  const slateEl = document.getElementById("dm-slate");
  const asofEl = document.getElementById("dm-asof");
  const ownTextEl = document.getElementById("dm-own-text");
  const ownStatusEl = document.getElementById("dm-own-status");
  const tabs = Array.from(document.querySelectorAll(".dm-tabs [role=tab]"));

  const state = { season: null, week: null, slate: null, data: null, tab: "summary", requestKey: null,
                  tableSort: { key: "final", dir: -1 }, tablePos: "ALL", tableQuery: "" };

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const num = (v, d) => (v == null ? "-" : Number(v).toFixed(d == null ? 1 : d));
  const money = (n) => (n == null ? "-" : "$" + Number(n).toLocaleString("en-US"));
  const INJ = { Q: "Q", D: "D", O: "OUT", IR: "IR" };

  function ownKey() {
    return `dfsriches:ownership:${state.season}:${state.week}`;
  }
  function loadOwnership() {
    try { return localStorage.getItem(ownKey()) || ""; } catch (e) { return ""; }
  }
  function saveOwnership(text) {
    try { text ? localStorage.setItem(ownKey(), text) : localStorage.removeItem(ownKey()); } catch (e) { /* private mode */ }
  }

  function popBadge(p) {
    if (p.ownership != null) return `<span class="dm-own-pct" title="User-provided projected ownership">${num(p.ownership, 1)}%</span>`;
    if (!p.popularity) return '<span class="dm-muted" title="No ownership data">-</span>';
    return `<span class="dm-pop dm-pop-${p.popularity.toLowerCase()}" title="Popularity estimate from value and projection rank at the position -- not ownership data">est. ${esc(p.popularity)}</span>`;
  }
  function uncBadge(p) {
    if (!p.uncertainty_label) return "";
    const tip = (p.uncertainty_reasons || []).join("; ") || "Outcome range at the position";
    return `<span class="dm-unc dm-unc-${p.uncertainty_label.toLowerCase()}" title="${esc(tip)}">${esc(p.uncertainty_label)}</span>`;
  }
  function injBadge(p) {
    return p.injury && p.injury !== "Healthy" ? `<span class="dm-inj" title="DraftKings injury status">${esc(INJ[p.injury] || p.injury)}</span>` : "";
  }

  function playerList(title, cards, opts) {
    opts = opts || {};
    if (!cards || cards.length === 0) {
      return `<section class="dm-card"><h3>${esc(title)}</h3><p class="dm-muted">${esc(opts.empty || "None this week.")}</p></section>`;
    }
    const items = cards.map((c) => `
      <li>
        <div class="dm-li-top">
          <span class="tp-pos">${esc(c.position)}</span>
          <span class="dm-name">${esc(c.name)}</span>${injBadge(c)}
          <span class="dm-team">${esc(c.team)}${c.opponent ? " v " + esc(c.opponent) : ""}</span>
          <span class="dm-sal">${money(c.salary)}</span>
        </div>
        <div class="dm-li-nums">
          <span title="Final projection (consensus + adjustments)">Proj <b>${num(c.final)}</b></span>
          <span title="Ceiling (85th percentile)">Ceil ${num(c.ceiling)}</span>
          <span title="Points per $1,000 of salary">${num(c.value, 2)}/$1k</span>
          ${popBadge(c)} ${uncBadge(c)}
        </div>
        ${c.reason ? `<div class="dm-reason">${esc(c.reason)}</div>` : ""}
      </li>`).join("");
    return `<section class="dm-card"><h3>${esc(title)}</h3>${opts.note ? `<p class="dm-note">${esc(opts.note)}</p>` : ""}<ol class="dm-list">${items}</ol></section>`;
  }

  function stackList(title, stacks) {
    if (!stacks || stacks.length === 0) return `<section class="dm-card"><h3>${esc(title)}</h3><p class="dm-muted">No stack with a playable QB, pass catcher and bring-back.</p></section>`;
    const items = stacks.map((s) => `
      <li>
        <div class="dm-li-top"><span class="dm-name">${esc(s.team)}: ${esc(s.type)}</span><span class="dm-sal">${money(s.salary)}</span></div>
        <div class="dm-stack-players">${s.players.map((p) => `<span><span class="tp-pos">${esc(p.position)}</span> ${esc(p.name)}</span>`).join("")}</div>
        <div class="dm-li-nums"><span>Proj <b>${num(s.final)}</b></span><span>Ceil ${num(s.ceiling)}</span><span title="Stack ceiling minus 3.5x its salary in $1k">Edge ${s.score > 0 ? "+" : ""}${num(s.score)}</span></div>
        <div class="dm-reason">${esc(s.reason)}</div>
      </li>`).join("");
    return `<section class="dm-card"><h3>${esc(title)}</h3><ol class="dm-list">${items}</ol></section>`;
  }

  function newsList(items) {
    if (!items || items.length === 0) return `<section class="dm-card"><h3>Biggest news &amp; context changes</h3><p class="dm-muted">No injuries or model adjustments of note.</p></section>`;
    return `<section class="dm-card"><h3>Biggest news &amp; context changes</h3><ol class="dm-list">${items.map((n) => `
      <li><div class="dm-li-top"><span class="dm-tag dm-tag-${esc(n.kind)}">${n.kind === "model" ? "Model" : "Sourced"}</span><span class="dm-muted">${esc(n.source)}</span></div>
      <div class="dm-reason">${esc(n.text)}</div></li>`).join("")}</ol></section>`;
  }

  function constructionList(items) {
    if (!items || items.length === 0) return "";
    return `<section class="dm-card"><h3>GPP lineup constructions</h3><ol class="dm-list">${items.map((c) => `
      <li><div class="dm-li-top"><span class="dm-name">${esc(c.name)}</span><span class="dm-muted">${esc(c.lineups.join(", "))}</span></div>
      <div class="dm-reason">${esc(c.description)}</div></li>`).join("")}</ol></section>`;
  }

  function renderSummary(d) {
    const s = d.summary;
    const ownNote = d.ownership.provided ? "" : "Popularity is an estimate (no ownership data connected).";
    return `<div class="dm-grid">
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

  function renderPool(d) {
    return `<div class="dm-grid">
      ${playerList("Top DFS plays (core)", d.top_plays, { note: "Final projection weighted by value vs the position median." })}
      ${playerList("Best values", d.summary.best_values)}
      ${playerList("GPP leverage", d.summary.leverage, { note: d.ownership.provided ? "" : "High-ceiling players the popularity estimate expects to be less rostered." })}
      ${playerList("Chalk worth eating", d.chalk.eat, { note: d.ownership.provided ? "" : "Chalk = popularity estimate, not ownership data." })}
      ${playerList("Likely over-owned", d.chalk.over_owned, { empty: "No chalk flagged for extra risk." })}
      ${playerList("Salary savers", d.salary_savers)}
      ${playerList("Fades / caution", d.fades, { empty: "Nothing flagged." })}
    </div>`;
  }

  function renderGames(d) {
    const rows = d.environments.map((e) => `
      <tr>
        <th scope="row">${esc(e.game)}<div class="dm-muted">${esc(e.kickoff || "")}</div></th>
        <td class="num">${num(e.total)}</td>
        <td class="num">${esc(e.away)} ${num(e.away_implied)} / ${esc(e.home)} ${num(e.home_implied)}</td>
        <td class="num">${num(e.top10_final)}</td>
        <td class="num">${num(e.top10_ceiling)}</td>
        <td>${esc(e.notes.filter((n) => n.startsWith("top-10")).join("; "))}</td>
      </tr>`).join("");
    const stacks = d.environments.map((e) => {
      const list = d.stacks_by_game[e.game] || [];
      return list.length ? stackList(`${e.game} stacks`, list) : "";
    }).join("");
    return `<section class="dm-card dm-wide"><h3>Best game environments</h3>
      <p class="dm-note">Sorted by Vegas total (nflverse closing lines). "Top-10 proj/ceiling" sums the game's ten best Final projections / ceilings.</p>
      <div class="dm-table-wrap"><table class="dm-table"><thead><tr><th scope="col">Game</th><th scope="col">Total</th><th scope="col">Implied</th><th scope="col">Top-10 proj</th><th scope="col">Top-10 ceil</th><th scope="col">Pace</th></tr></thead><tbody>${rows}</tbody></table></div>
    </section><div class="dm-grid">${stacks}</div>`;
  }

  const TABLE_COLS = [
    ["name", "Player"], ["position", "Pos"], ["salary", "Salary"], ["consensus", "Consensus"], ["final", "Final"],
    ["floor", "Floor"], ["median", "Median"], ["ceiling", "Ceiling"], ["value", "Value"], ["ownership", "Own"], ["uncertainty", "Uncertainty"],
  ];

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
    const head = TABLE_COLS.map(([k, label]) => {
      const sorted = key === k ? (dir === -1 ? "descending" : "ascending") : "none";
      return `<th scope="col" aria-sort="${sorted}"><button type="button" class="dm-sort" data-sort="${k}">${label}${key === k ? (dir === -1 ? " ▼" : " ▲") : ""}</button></th>`;
    }).join("");
    const body = rows.map((p) => {
      const adj = (p.adjustments || []).map((a) => `${a.kind === "model" ? "Model" : "Sourced"}: ${a.text}`).join("\n") || "No adjustments: Final = consensus";
      return `<tr class="${p.final === 0 ? "dm-row-out" : ""}">
        <th scope="row">${esc(p.name)} ${injBadge(p)}<div class="dm-muted">${esc(p.team)} v ${esc(p.opponent)}</div></th>
        <td>${esc(p.position)}</td>
        <td class="num">${money(p.salary)}</td>
        <td class="num" title="${esc(sourceTip(p, d))}">${num(p.consensus)} <span class="dm-muted">(${p.n_sources})</span></td>
        <td class="num" title="${esc(adj)}"><b>${num(p.final)}</b>${(p.adjustments || []).some((a) => a.kind === "model") ? '<span class="dm-adj" aria-label="model-adjusted">*</span>' : ""}</td>
        <td class="num">${num(p.floor)}</td>
        <td class="num">${num(p.median)}</td>
        <td class="num" title="${p.app_ceiling != null ? "Blend of the calibrated 85th percentile and the matchup Ceiling (" + num(p.app_ceiling) + ")" : "Calibrated 85th percentile"}">${num(p.ceiling)}</td>
        <td class="num">${num(p.value, 2)}</td>
        <td class="num">${popBadge(p)}</td>
        <td>${uncBadge(p)}</td>
      </tr>`;
    }).join("");
    const posBtns = ["ALL", "QB", "RB", "WR", "TE", "DST"].map((pos) => `<button type="button" class="dm-chip" data-pos="${pos}" aria-pressed="${state.tablePos === pos}">${pos}</button>`).join("");
    return `<section class="dm-card dm-wide">
      <h3>Player projection table</h3>
      <p class="dm-note">Consensus = equal-weight mean of the sources that project the player (count in parentheses; hover for each source, or "missing").
        Final = consensus + labeled adjustments (* = model matchup adjustment; hover for details). Floor / Median = 15th / 50th percentile of past
        actual-vs-consensus outcomes at the position and projection range.</p>
      <div class="dm-table-tools">${posBtns}<input type="search" id="dm-search" placeholder="Search player or team" value="${esc(state.tableQuery)}" aria-label="Search player or team" /></div>
      <div class="dm-table-wrap dm-table-tall"><table class="dm-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
      <p class="dm-note">${rows.length} players. ${d.no_source_players.length ? "Playable with no source projection (left blank, not estimated): " + esc(d.no_source_players.join(", ")) : ""}</p>
    </section>`;
  }

  function lineupCard(lu, d) {
    const own = lu.ownership != null ? `${num(lu.ownership, 1)}% total own` : (d.ownership.provided ? "ownership incomplete" : `${lu.chalk_count} est. chalk`);
    const rows = lu.players.map((p) => `<tr><td>${esc(p.slot)}</td><th scope="row">${esc(p.name)} ${injBadge(p)}<span class="dm-muted"> ${esc(p.team)}</span></th>
      <td class="num">${money(p.salary)}</td><td class="num">${num(p.final)}</td><td class="num">${num(p.ceiling)}</td><td class="num">${popBadge(p)}</td></tr>`).join("");
    const names = lu.players.map((p) => `${p.slot} ${p.name}`).join("\n");
    return `<article class="dm-lineup">
      <header><h4>${esc(lu.label)}</h4><span class="dm-muted">${esc(lu.construction)}</span></header>
      <div class="dm-li-nums"><span>${money(lu.salary)}</span><span>Proj <b>${num(lu.final)}</b></span><span>Floor ${num(lu.floor)}</span><span>Ceil ${num(lu.ceiling)}</span><span>${esc(own)}</span></div>
      <p class="dm-reason">${esc(lu.stack)}</p>
      <table class="dm-table dm-lineup-table"><thead><tr><th scope="col">Slot</th><th scope="col">Player</th><th scope="col">Salary</th><th scope="col">Proj</th><th scope="col">Ceil</th><th scope="col">Own</th></tr></thead><tbody>${rows}</tbody></table>
      <button type="button" class="dm-btn dm-btn-quiet dm-copy" data-copy="${esc(names)}">Copy</button>
    </article>`;
  }

  function renderLineups(d) {
    const L = d.lineups;
    const group = (title, note, list) => `<section class="dm-card dm-wide"><h3>${esc(title)}</h3><p class="dm-note">${esc(note)}</p>
      <div class="dm-lineups">${list.length ? list.map((lu) => lineupCard(lu, d)).join("") : '<p class="dm-muted">Could not build these lineups from the current pool.</p>'}</div></section>`;
    return group("High-floor lineups (5)", "Maximize Floor + Final projection; each differs from the others by at least 2 players.", L.high_floor)
      + constructionList(L.constructions)
      + group("GPP lineups (10)", "Maximize ceiling within each construction (2 lineups each); QB stacks with a bring-back, no DST facing your own players, at least 3 players different from every other GPP lineup, max 6 of 10 for any player.", L.gpp)
      + group("Contrarian GPP lineups (5)", (d.ownership.provided ? "Ceiling discounted by user-provided ownership" : "Ceiling discounted by the popularity estimate") + "; a different QB stack in each, from outside the two highest-total games.", L.contrarian);
  }

  function renderMethod(d) {
    const src = d.sources.map((s) => `<tr><th scope="row">${esc(s.label)}</th><td class="num">${s.available ? s.matched_on_slate : "-"}</td><td>${s.available ? esc(s.fetched_at || "") : "unavailable this week"}</td></tr>`).join("");
    const un = d.unavailable_sources.map((u) => `<li><b>${esc(u.label)}</b>: ${esc(u.reason)}</li>`).join("");
    const acc = d.accuracy || {};
    const rel = acc.relative_mae || {};
    const labels = Object.fromEntries(d.sources.map((s) => [s.key, s.label]));
    const accRows = Object.entries(rel).map(([pos, bySrc]) => `<tr><th scope="row">${esc(pos)}</th>${Object.keys(labels).map((k) => {
      const v = bySrc[k];
      return `<td class="num" title="${v ? `MAE ${v.mae} vs Sleeper ${v.sleeper_mae} on the same ${v.games} player-games` : "No graded history (CBS serves only the current week)"}">${v ? v.ratio.toFixed(3) : "-"}</td>`;
    }).join("")}<td class="num">${acc.consensus && acc.consensus[pos] ? `${acc.consensus[pos].mae_consensus} vs ${acc.consensus[pos].mae_sleeper}` : "-"}</td><td>${esc((d.weighting || {})[pos] || "")}</td></tr>`).join("");
    return `<div class="dm-grid">
      <section class="dm-card"><h3>Sources this week</h3>
        <table class="dm-table"><thead><tr><th scope="col">Source</th><th scope="col">Players matched</th><th scope="col">Fetched (UTC)</th></tr></thead><tbody>${src}</tbody></table>
        <p class="dm-note">FantasyPros' public page lists only the top 10 per position (the rest needs a premium account). FFToday has no DST lines or fumbles. Sources refresh every 2 hours; DraftKings salaries and injury statuses every 5 minutes.</p>
        <h4>Not used</h4><ul class="dm-bullets">${un}</ul>
      </section>
      <section class="dm-card dm-wide"><h3>Historical accuracy &amp; weighting</h3>
        <p class="dm-note">Each source's mean absolute error (actual DK points) divided by Sleeper's on the same player-games, ${esc((acc.weeks || []).length)} weeks graded (${esc((acc.weeks || [])[0] || "")} to ${esc((acc.weeks || []).slice(-1)[0] || "")}). Below 1.000 = more accurate. Weights would be 1/MAE only if sources differed by more than 5%.</p>
        <div class="dm-table-wrap"><table class="dm-table"><thead><tr><th scope="col">Pos</th>${Object.values(labels).map((l) => `<th scope="col">${esc(l)}</th>`).join("")}<th scope="col">MAE consensus vs Sleeper</th><th scope="col">Weighting used</th></tr></thead><tbody>${accRows}</tbody></table></div>
      </section>
      <section class="dm-card dm-wide"><h3>How the numbers are built</h3><ul class="dm-bullets">
        <li><b>Consensus</b>: every source's projected stat line scored with DraftKings rules (no 100/300-yard bonuses, which overstate a projected mean), then mean, median, range, SD and source count. Missing sources stay missing.</li>
        <li><b>Final</b> = consensus, then only: DraftKings injury status (sourced: OUT/Doubtful/IR = 0; Questionable kept, uncertainty raised) and the backtested matchup nudge (model: +/-5% max). Workload, news and game environment are already in the sources' lines; multiplying them in again made the 2025 backtest worse, so they're shown as context.</li>
        <li><b>Floor / Median</b>: 15th / 50th percentile of actual / consensus in past weeks, by position and projection range. <b>Ceiling</b>: average of that 85th percentile and the page's matchup Ceiling.</li>
        <li><b>Uncertainty</b>: source disagreement (SD / mean), few sources, Questionable status, and the position's outcome spread; High / Medium / Low are thirds of the slate.</li>
        <li><b>Ownership</b>: ${esc(d.ownership.note)} ${d.ownership.provided ? `(${d.ownership.matched} players matched)` : ""}</li>
        <li><b>Lineups</b>: exact integer programs on DraftKings' rules. Questionable players count 90% in lineup objectives (risk they sit), without changing their projection.</li>
      </ul></section>
    </div>`;
  }

  function render() {
    const d = state.data;
    if (!d) return;
    if (!d.available) {
      panelEl.innerHTML = `<p class="dm-muted">${esc(d.reason)}</p>`;
      return;
    }
    const view = { summary: renderSummary, pool: renderPool, games: renderGames, table: renderTable, lineups: renderLineups, method: renderMethod }[state.tab];
    panelEl.innerHTML = view(d);
  }

  function selectTab(name) {
    state.tab = name;
    for (const t of tabs) t.setAttribute("aria-selected", String(t.dataset.tab === name));
    render();
  }

  async function load(force) {
    state.season = Number(document.getElementById("season-input").value);
    state.week = Number(document.getElementById("week-input").value);
    const own = loadOwnership();
    ownTextEl.value = own;
    const key = `${state.season}|${state.week}|${state.slate || ""}|${own.length}`;
    state.requestKey = key;
    asofEl.textContent = "Building model...";
    if (force || !state.data) panelEl.innerHTML = '<p class="dm-muted">Pulling every source and building lineups (can take ~15s on a cold start)...</p>';
    const params = new URLSearchParams({ season: state.season, week: state.week });
    if (state.slate) params.set("slate_id", state.slate);
    try {
      const res = await fetch(`/api/dfs-model?${params}`, own
        ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ownership: own }) }
        : undefined);
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `Request failed: ${res.status}`);
      if (state.requestKey !== key) return;   // a newer request replaced this one
      state.data = body;
      if (body.available) {
        state.slate = body.slate.slate_id;
        slateEl.innerHTML = body.slates.map((s) => `<option value="${esc(s.slate_id)}"${s.slate_id === body.slate.slate_id ? " selected" : ""}>${esc(s.label)}</option>`).join("");
        const when = new Date(body.generated_at);
        asofEl.textContent = `Built ${when.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })} from ${body.sources.filter((s) => s.available).length} sources`;
        ownStatusEl.textContent = body.ownership.provided ? `(${body.ownership.matched} matched)` : "";
      } else {
        slateEl.innerHTML = "";
        asofEl.textContent = "";
      }
      render();
    } catch (err) {
      if (state.requestKey !== key) return;
      asofEl.textContent = "";
      panelEl.innerHTML = `<p class="dm-error">Could not build the DFS model: ${esc(err.message)}</p>`;
    }
  }

  for (const t of tabs) t.addEventListener("click", () => selectTab(t.dataset.tab));
  document.querySelector(".dm-tabs").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const i = tabs.findIndex((t) => t.dataset.tab === state.tab);
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    next.focus();
    selectTab(next.dataset.tab);
  });
  slateEl.addEventListener("change", () => { state.slate = slateEl.value; load(true); });
  document.getElementById("dm-refresh").addEventListener("click", () => load(true));
  document.getElementById("load-week-btn").addEventListener("click", () => { state.slate = null; state.data = null; load(true); });
  document.getElementById("dm-own-apply").addEventListener("click", () => { saveOwnership(ownTextEl.value.trim()); load(true); });
  document.getElementById("dm-own-clear").addEventListener("click", () => { ownTextEl.value = ""; saveOwnership(""); load(true); });

  panelEl.addEventListener("click", (e) => {
    const sortBtn = e.target.closest("[data-sort]");
    if (sortBtn) {
      const k = sortBtn.dataset.sort;
      state.tableSort = { key: k, dir: state.tableSort.key === k ? -state.tableSort.dir : (k === "name" || k === "position" ? 1 : -1) };
      render();
      return;
    }
    const chip = e.target.closest("[data-pos]");
    if (chip) { state.tablePos = chip.dataset.pos; render(); return; }
    const copy = e.target.closest("[data-copy]");
    if (copy) {
      navigator.clipboard && navigator.clipboard.writeText(copy.dataset.copy).then(() => {
        copy.textContent = "Copied";
        setTimeout(() => { copy.textContent = "Copy"; }, 1500);
      }).catch(() => {});
    }
  });
  panelEl.addEventListener("input", (e) => {
    if (e.target.id !== "dm-search") return;
    state.tableQuery = e.target.value;
    const pos = e.target.selectionStart;
    render();
    const again = document.getElementById("dm-search");
    if (again) { again.focus(); again.setSelectionRange(pos, pos); }
  });

  load(true);
})();
