// Lineup-building rules, ported from the website's static/lineups.js so the
// app and the site build lineups the same way.
import { SALARY_CAP } from '@/constants/config';

// Slot order matters: position slots come before FLEX so a tap fills the
// natural slot first and only spills into FLEX once those are full.
const TEMPLATES: Record<SlateType, SlotDef[]> = {
  classic: [
    { label: 'QB', allow: ['QB'] },
    { label: 'RB', allow: ['RB'] },
    { label: 'RB', allow: ['RB'] },
    { label: 'WR', allow: ['WR'] },
    { label: 'WR', allow: ['WR'] },
    { label: 'WR', allow: ['WR'] },
    { label: 'TE', allow: ['TE'] },
    { label: 'FLEX', allow: ['RB', 'WR', 'TE'] },
    { label: 'DST', allow: ['DST'] },
  ],
  showdown: [
    { label: 'CPT', rosterSlot: 'CPT' },
    { label: 'FLEX', rosterSlot: 'FLEX' },
    { label: 'FLEX', rosterSlot: 'FLEX' },
    { label: 'FLEX', rosterSlot: 'FLEX' },
    { label: 'FLEX', rosterSlot: 'FLEX' },
    { label: 'FLEX', rosterSlot: 'FLEX' },
  ],
};

export function template(slateType: SlateType): SlotDef[] {
  return TEMPLATES[slateType] ?? TEMPLATES.classic;
}

export function emptyLineup(slateType: SlateType): BuilderLineup {
  return template(slateType).map(() => null);
}

function slotAccepts(def: SlotDef, player: Player): boolean {
  if (def.rosterSlot) return player.roster_slot === def.rosterSlot;
  return (def.allow ?? []).includes(player.position);
}

// Showdown lists each real player twice (CPT + FLEX, different draftable
// ids); this identifies the underlying player across both.
function samePerson(a: Player, b: Player): boolean {
  return a.name === b.name && a.team === b.team;
}

export function indexOfPlayer(slots: BuilderLineup, player: Player): number {
  return slots.findIndex((p) => p != null && p.dk_draftable_id === player.dk_draftable_id);
}

export type AddResult = { ok: true; slots: BuilderLineup; index: number } | { ok: false; reason: string };

export function addPlayer(slots: BuilderLineup, slateType: SlateType, player: Player): AddResult {
  if (indexOfPlayer(slots, player) !== -1) return { ok: false, reason: `${player.name} is already in this lineup.` };
  const dupe = slots.find((p) => p != null && samePerson(p, player));
  if (dupe) return { ok: false, reason: `${player.name} is already in this lineup as ${dupe.roster_slot || dupe.position}.` };
  const defs = template(slateType);
  const index = defs.findIndex((def, i) => !slots[i] && slotAccepts(def, player));
  if (index === -1) {
    const eligible = [...new Set(defs.filter((d) => slotAccepts(d, player)).map((d) => d.label))];
    return { ok: false, reason: `No open ${eligible.join('/') || player.position} slot for ${player.name}.` };
  }
  const next = slots.slice();
  next[index] = player;
  return { ok: true, slots: next, index };
}

export function removeAt(slots: BuilderLineup, index: number): BuilderLineup {
  const next = slots.slice();
  next[index] = null;
  return next;
}

/** Fills a builder lineup from a saved optimal lineup, matching players by draftable id. */
export function fromOptimal(lineup: OptimalLineup, slateType: SlateType, pool: Player[]): BuilderLineup {
  const byId = new Map(pool.map((p) => [p.dk_draftable_id, p]));
  let slots = emptyLineup(slateType);
  for (const lp of lineup.players) {
    const player = byId.get(lp.dk_draftable_id);
    if (!player) continue;
    const res = addPlayer(slots, slateType, player);
    if (res.ok) slots = res.slots;
  }
  return slots;
}

/**
 * Which pool players still fit: an open slot that takes them, not already
 * rostered (Showdown: not as the other of CPT/FLEX), and a salary that leaves
 * enough to fill every other open slot with the cheapest eligible players.
 */
export function fitChecker(slots: BuilderLineup, slateType: SlateType, pool: Player[]) {
  const defs = template(slateType);
  const filled = slots.filter((p): p is Player => p != null);
  const remaining = SALARY_CAP - filled.reduce((s, p) => s + p.salary, 0);
  const open = defs.map((_, i) => i).filter((i) => !slots[i]);
  const available = pool.filter((p) => !filled.some((f) => samePerson(f, p))).sort((a, b) => a.salary - b.salary);
  const cheapest: Record<number, Player[]> = {};
  for (const i of open) cheapest[i] = available.filter((p) => slotAccepts(defs[i], p));

  return (player: Player): { ok: boolean; reason: string | null } => {
    if (indexOfPlayer(slots, player) !== -1) return { ok: true, reason: 'In this lineup' };
    const dupe = filled.find((p) => samePerson(p, player));
    if (dupe) return { ok: false, reason: `Already in as ${dupe.roster_slot || dupe.position}` };
    const idx = open.find((i) => slotAccepts(defs[i], player));
    if (idx === undefined) return { ok: false, reason: 'No open slot for this position' };
    let need = 0;
    const taken = [player];
    const others = open.filter((i) => i !== idx).sort((a, b) => cheapest[a].length - cheapest[b].length);
    for (const i of others) {
      const pick = cheapest[i].find((p) => !taken.some((t) => samePerson(t, p)));
      if (!pick) return { ok: false, reason: 'Not enough eligible players left' };
      taken.push(pick);
      need += pick.salary;
    }
    if (player.salary + need > remaining) {
      return { ok: false, reason: `Leaves too little salary for the other ${others.length} slot${others.length === 1 ? '' : 's'}` };
    }
    return { ok: true, reason: null };
  };
}

export function summarize(slots: BuilderLineup, slateType: SlateType): LineupSummary {
  const filled = slots.filter((p): p is Player => p != null);
  const salary = filled.reduce((s, p) => s + p.salary, 0);
  const proj = filled.reduce((s, p) => s + (p.proj_points || 0), 0);
  const ceiling = filled.reduce((s, p) => s + (p.ceiling || 0), 0);
  const open = slots.length - filled.length;
  const remaining = SALARY_CAP - salary;

  const errors: string[] = [];
  if (open > 0) errors.push(`${open} open slot${open === 1 ? '' : 's'}`);
  if (remaining < 0) errors.push(`Over the $50,000 cap by $${(-remaining).toLocaleString('en-US')}`);
  if (open === 0) {
    if (slateType === 'showdown') {
      if (new Set(filled.map((p) => p.team)).size < 2) errors.push('Needs players from both teams');
    } else if (new Set(filled.map((p) => p.game_info)).size < 2) {
      errors.push('Needs players from at least 2 games');
    }
  }

  return {
    salary,
    remaining,
    avgRemaining: open > 0 ? Math.floor(remaining / open) : null,
    proj: Math.round(proj * 100) / 100,
    ceiling: Math.round(ceiling * 100) / 100,
    filled: filled.length,
    total: slots.length,
    valid: errors.length === 0,
    errors,
  };
}
