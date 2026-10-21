import type { BuildField } from '@/components/LineupBuilder';

export const FIELD_LABEL: Record<OwnershipContest, string> = { cash: 'Cash', small_gpp: 'Small-field GPP', large_gpp: 'Large-field GPP' };

/** A contest field's ownership (and, for cash, the model floor) by DK draftable id, for the lineup builder. */
export function buildField(players: PlayPlayer[], field: OwnershipContest): BuildField {
  const ownership = new Map<number, number>();
  const floor = new Map<number, number>();
  const env = new Map<number, number>();
  const leverage = new Map<number, number>();
  const leverageDetail = new Map<number, LeverageDetail>();
  for (const p of players) {
    const own = p.ownership[field];
    if (own != null) ownership.set(p.id, own);
    floor.set(p.id, p.floor);
    if (p.parts.env != null) env.set(p.id, p.parts.env);
    // Fair minus projected ownership for this contest (app/leverage.py; cash: odds of 2.5x salary).
    if (p.leverage != null) leverage.set(p.id, p.leverage);
    if (p.leverage_detail) leverageDetail.set(p.id, p.leverage_detail);
  }
  return { label: FIELD_LABEL[field], ownership, floor: field === 'cash' ? floor : undefined, env, leverage, leverageDetail };
}
