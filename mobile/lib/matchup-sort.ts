import { matchupScore } from '@/lib/matchups-context';

// Starters and rotation players (committee backs etc.) first, then backups, then players who can't play.
const ROLE_TIER: Record<string, number> = { starter: 0, rotation: 0, backup: 1, out: 2 };

interface Sortable {
  opponent?: string | null;
  position: string;
  role?: PlayerRole | null;
}

/**
 * Sort by matchup strength (softest first) without letting one soft defense's
 * whole depth chart crowd the top: starters and rotation players are ordered
 * by their opponent's rank, then backups the same way. Ties break on
 * projection.
 */
export function sortByMatchup<T extends Sortable>(
  items: T[],
  lookup: (opponent: string | null | undefined, position: string | null | undefined) => { fp_rank: number; eff_rank: number } | null,
  projection: (t: T) => number,
): T[] {
  const keyed = items.map((t) => {
    const m = lookup(t.opponent, t.position);
    return { t, tier: ROLE_TIER[t.role ?? 'backup'] ?? 1, score: m ? matchupScore(m) : -1, proj: projection(t) };
  });
  keyed.sort((a, b) => a.tier - b.tier || b.score - a.score || b.proj - a.proj);
  return keyed.map((k) => k.t);
}

const ROLE_LABEL: Record<PlayerRole, string> = {
  starter: 'Starter',
  rotation: 'Rotation',
  backup: 'Backup',
  out: 'Out',
};

/** "Rotation · 48% snaps" for meta lines; empty for DSTs and unknown roles. */
export function roleText(p: { position: string; role?: PlayerRole | null; snap_pct?: number | null }): string {
  if (!p.role || p.position === 'DST') return '';
  const snaps = p.snap_pct != null ? ` · ${Math.round(p.snap_pct)}% snaps` : '';
  return `${ROLE_LABEL[p.role]}${snaps}`;
}
