/* Shared by every page: the one season/week selector, and small helpers.
   The server renders the header with the current NFL week (or the URL's
   ?season=&week=). Changing either input updates the URL, every nav link and
   this tab's session, then tells the page to reload -- no Load button. */
(function () {
  "use strict";

  const SESSION_KEY = "dfsriches:week";
  const seasonEl = document.getElementById("season-input");
  const weekEl = document.getElementById("week-input");
  const listeners = [];
  const inFlight = new Map();

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const money = (n) => (n == null ? "-" : "$" + Number(n).toLocaleString("en-US"));

  function valid(season, week) {
    return Number.isInteger(season) && season >= 2000 && season <= 2100 && Number.isInteger(week) && week >= 1 && week <= 18;
  }

  function current() {
    return { season: Number(seasonEl.value), week: Number(weekEl.value) };
  }

  function sync() {
    const { season, week } = current();
    const url = new URL(location.href);
    url.searchParams.set("season", season);
    url.searchParams.set("week", week);
    history.replaceState(history.state, "", url);
    for (const a of document.querySelectorAll(".page-nav a")) {
      const target = new URL(a.getAttribute("href"), location.origin);
      target.searchParams.set("season", season);
      target.searchParams.set("week", week);
      a.setAttribute("href", target.pathname + target.search);
    }
    try { sessionStorage.setItem(SESSION_KEY, JSON.stringify({ season, week })); } catch (e) { /* storage blocked */ }
  }

  // No explicit URL: return to the week chosen earlier in this tab, if any.
  const params = new URLSearchParams(location.search);
  if (!params.has("season") && !params.has("week")) {
    try {
      const saved = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "null");
      if (saved && valid(saved.season, saved.week)) {
        seasonEl.value = saved.season;
        weekEl.value = saved.week;
      }
    } catch (e) { /* storage blocked */ }
  }
  sync();

  let last = JSON.stringify(current());
  let timer = null;
  function onInput() {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const next = current();
      const key = JSON.stringify(next);
      const bad = !valid(next.season, next.week);
      seasonEl.setAttribute("aria-invalid", String(bad && !(next.season >= 2000 && next.season <= 2100)));
      weekEl.setAttribute("aria-invalid", String(bad && !(next.week >= 1 && next.week <= 18)));
      if (bad || key === last) return;
      last = key;
      sync();
      for (const fn of listeners) fn(next);
    }, 350);
  }
  for (const el of [seasonEl, weekEl]) {
    el.addEventListener("input", onInput);
    el.addEventListener("change", onInput);
  }
  document.getElementById("week-form").addEventListener("submit", (e) => { e.preventDefault(); onInput(); });

  /* fetch JSON; a newer request on the same channel aborts the older one, so a
     slow response for a previous week can never overwrite the current one. */
  async function getJson(url, channel, options) {
    let controller = null;
    if (channel) {
      if (inFlight.has(channel)) inFlight.get(channel).abort();
      controller = new AbortController();
      inFlight.set(channel, controller);
    }
    try {
      const res = await fetch(url, { ...(options || {}), signal: controller ? controller.signal : undefined });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `Request failed: ${res.status}`);
      return body;
    } finally {
      if (channel && inFlight.get(channel) === controller) inFlight.delete(channel);
    }
  }

  const isAbort = (err) => err && err.name === "AbortError";

  window.DFS = {
    get season() { return current().season; },
    get week() { return current().week; },
    onWeekChange: (fn) => listeners.push(fn),
    getJson,
    isAbort,
    esc,
    money,
  };
})();
