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

  // Game weather (app/weather.py) as a compact badge; the tooltip carries venue, source and projection impact.
  function weatherBadge(w, opts) {
    if (!w) return "";
    const sev = w.roof === "dome" ? "indoor" : w.roof === "retractable" ? "roof" : w.available ? (w.severity || "good") : "na";
    let text = w.roof === "dome" ? "Dome" : w.summary || "Weather unavailable";
    if (opts && opts.short && w.roof === "retractable") text = "Retractable roof";
    const tip = [w.venue, w.roof === "retractable" ? w.summary : null, w.impact ? `Projection impact: ${w.impact}` : null,
      w.long_range ? "Long-range forecast (adjustments at half strength)" : null, w.source].filter(Boolean).join(" · ");
    return `<span class="wx wx-${sev}" title="${esc(tip)}">${esc(text)}</span>`;
  }

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

  /* Sign-in: the API is for signed-in accounts. clerk-js (loaded by the page)
     shares the new app's session on this domain and hands out a fresh session
     token for each request; signed out, the visitor goes to the app's sign-in. */
  const signInRequired = document.body.dataset.requireSignIn === "1";
  const clerkReady = !signInRequired ? Promise.resolve(null) : new Promise((resolve, reject) => {
    const started = Date.now();
    (function wait() {
      if (window.Clerk) return void window.Clerk.load().then(() => resolve(window.Clerk), reject);
      if (Date.now() - started > 20000) return void reject(new Error("Couldn't load sign-in. Check your connection and reload."));
      setTimeout(wait, 50);
    })();
  });
  clerkReady.then((clerk) => { if (clerk && !clerk.session) location.assign("/sign-in"); }, () => {});

  async function authHeaders() {
    const clerk = await clerkReady;
    if (!clerk) return {};
    if (!clerk.session) {
      location.assign("/sign-in");
      throw new Error("Sign in to Riches Analytics to see this.");
    }
    const token = await clerk.session.getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

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
      const opts = options || {};
      const headers = { ...(opts.headers || {}), ...(await authHeaders()) };
      const res = await fetch(url, { ...opts, headers, signal: controller ? controller.signal : undefined });
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
    weatherBadge,
    money,
  };
})();
