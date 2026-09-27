(function (root) {
  "use strict";

  const SALARY_CAP = 50000;
  const MAX_LINEUPS = 5;

  // Slot order matters: position slots come before FLEX so a click fills the
  // natural slot first and only spills into FLEX once those are full.
  const TEMPLATES = {
    classic: [
      { label: "QB", allow: ["QB"] },
      { label: "RB", allow: ["RB"] },
      { label: "RB", allow: ["RB"] },
      { label: "WR", allow: ["WR"] },
      { label: "WR", allow: ["WR"] },
      { label: "WR", allow: ["WR"] },
      { label: "TE", allow: ["TE"] },
      { label: "FLEX", allow: ["RB", "WR", "TE"] },
      { label: "DST", allow: ["DST"] },
    ],
    showdown: [
      { label: "CPT", rosterSlot: "CPT" },
      { label: "FLEX", rosterSlot: "FLEX" },
      { label: "FLEX", rosterSlot: "FLEX" },
      { label: "FLEX", rosterSlot: "FLEX" },
      { label: "FLEX", rosterSlot: "FLEX" },
      { label: "FLEX", rosterSlot: "FLEX" },
    ],
  };

  function template(slateType) {
    return TEMPLATES[slateType] || TEMPLATES.classic;
  }

  function emptyLineup(slateType) {
    return template(slateType).map(() => null);
  }

  function slotAccepts(def, player) {
    if (def.rosterSlot) return player.roster_slot === def.rosterSlot;
    return def.allow.includes(player.position);
  }

  // Showdown lists each real player twice (CPT row + FLEX row, different
  // draftable ids); this identifies the underlying player across both.
  function samePerson(a, b) {
    return a.name === b.name && a.team === b.team;
  }

  function indexOfPlayer(slots, player) {
    return slots.findIndex((p) => p && p.dk_draftable_id === player.dk_draftable_id);
  }

  function addPlayer(slots, slateType, player) {
    if (indexOfPlayer(slots, player) !== -1) {
      return { ok: false, reason: `${player.name} is already in this lineup.` };
    }
    const dupe = slots.find((p) => p && samePerson(p, player));
    if (dupe) {
      return { ok: false, reason: `${player.name} is already in this lineup as ${dupe.roster_slot || dupe.position}.` };
    }
    const defs = template(slateType);
    const idx = defs.findIndex((def, i) => !slots[i] && slotAccepts(def, player));
    if (idx === -1) {
      const eligible = [...new Set(defs.filter((d) => slotAccepts(d, player)).map((d) => d.label))];
      return { ok: false, reason: `No open ${eligible.join("/") || player.position} slot for ${player.name}.` };
    }
    const next = slots.slice();
    next[idx] = player;
    return { ok: true, slots: next, index: idx };
  }

  // Which pool players can still go into this lineup: an open slot that takes
  // them, not already rostered (Showdown: not as the other of CPT/FLEX), and a
  // salary that leaves enough to fill every other open slot with the cheapest
  // eligible players left in the pool. Players already in the lineup always
  // "fit" so they stay visible to remove. Returns player -> {ok, reason}.
  function fitChecker(slots, slateType, pool) {
    const defs = template(slateType);
    const filled = slots.filter(Boolean);
    const remaining = SALARY_CAP - filled.reduce((s, p) => s + p.salary, 0);
    const open = defs.map((d, i) => i).filter((i) => !slots[i]);
    const available = pool.filter((p) => !filled.some((f) => samePerson(f, p))).sort((a, b) => a.salary - b.salary);
    const cheapest = {};
    for (const i of open) cheapest[i] = available.filter((p) => slotAccepts(defs[i], p));

    return function (player) {
      if (indexOfPlayer(slots, player) !== -1) return { ok: true, reason: "In this lineup" };
      const dupe = filled.find((p) => samePerson(p, player));
      if (dupe) return { ok: false, reason: `Already in this lineup as ${dupe.roster_slot || dupe.position}` };
      const idx = open.find((i) => slotAccepts(defs[i], player));
      if (idx === undefined) return { ok: false, reason: "No open slot for this position" };
      let need = 0;
      const taken = [player];
      const others = open.filter((i) => i !== idx).sort((a, b) => cheapest[a].length - cheapest[b].length);
      for (const i of others) {
        const pick = cheapest[i].find((p) => !taken.some((t) => samePerson(t, p)));
        if (!pick) return { ok: false, reason: "Not enough eligible players left to fill the lineup" };
        taken.push(pick);
        need += pick.salary;
      }
      if (player.salary + need > remaining) {
        return { ok: false, reason: `Leaves too little salary to fill the other ${others.length} slot${others.length === 1 ? "" : "s"}` };
      }
      return { ok: true, reason: null };
    };
  }

  function removeAt(slots, index) {
    const next = slots.slice();
    next[index] = null;
    return next;
  }

  function summarize(slots, slateType) {
    const filled = slots.filter(Boolean);
    const salary = filled.reduce((s, p) => s + p.salary, 0);
    const proj = filled.reduce((s, p) => s + (p.proj_points || 0), 0);
    const ceiling = filled.reduce((s, p) => s + (p.ceiling || 0), 0);
    const withSleeper = filled.filter((p) => p.sleeper_proj != null);
    const withOwn = filled.filter((p) => p.ownership != null);
    const ownSum = withOwn.reduce((s, p) => s + p.ownership, 0);
    const sleeperProj = withSleeper.reduce((s, p) => s + p.sleeper_proj, 0);
    const open = slots.length - filled.length;
    const remaining = SALARY_CAP - salary;

    const errors = [];
    if (open > 0) errors.push(`${open} open slot${open === 1 ? "" : "s"}`);
    if (remaining < 0) errors.push(`Over the $50,000 cap by $${(-remaining).toLocaleString("en-US")}`);
    if (open === 0) {
      if (slateType === "showdown") {
        if (new Set(filled.map((p) => p.team)).size < 2) errors.push("Needs players from both teams");
      } else if (new Set(filled.map((p) => p.game_info)).size < 2) {
        errors.push("Needs players from at least 2 games");
      }
    }

    return {
      salary,
      remaining,
      avgRemaining: open > 0 ? Math.floor(remaining / open) : null,
      proj: Math.round(proj * 100) / 100,
      ceiling: Math.round(ceiling * 100) / 100,
      sleeperProj: Math.round(sleeperProj * 100) / 100,
      sleeperCount: withSleeper.length,
      ownSum: Math.round(ownSum * 10) / 10,          // cumulative ownership of the rostered players
      ownCount: withOwn.length,
      ownAvg: withOwn.length ? Math.round((ownSum / withOwn.length) * 10) / 10 : null,
      filled: filled.length,
      total: slots.length,
      errors,
      valid: errors.length === 0,
    };
  }

  const api = { SALARY_CAP, MAX_LINEUPS, template, emptyLineup, addPlayer, removeAt, indexOfPlayer, summarize, fitChecker };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    root.DFSLineups = api;
  }
})(this);
