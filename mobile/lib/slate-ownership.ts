import { getDfsModel } from '@/lib/api';
import { createFetchCache, useCachedFetch } from '@/lib/cached-fetch';
import { useWeek } from '@/lib/week-context';

// DK draftable id -> expected ownership (%), per season:week:slate.
const cache = createFetchCache<Map<number, number>>();

/**
 * The DFS model's expected ownership for a Classic slate, keyed by DraftKings
 * draftable id -- for sorting the lineup builder. Loaded only when `enabled`
 * (the model is a heavy request); Showdown slates have no model, so null.
 */
export function useSlateOwnership(slate: Slate | null, enabled: boolean) {
  const { season, week } = useWeek();
  const classic = slate?.slate_type === 'classic';
  const key = slate && classic && season && week ? `${season}:${week}:${slate.slate_id}` : '';
  const { data, error } = useCachedFetch(cache, enabled ? key : '', async () => {
    const m = await getDfsModel(season!, week!, slate!.slate_id);
    const map = new Map<number, number>();
    for (const p of m.table ?? []) if (p.ownership != null) map.set(p.id, p.ownership);
    return map;
  });
  // Already loaded for this slate: available even while not `enabled`.
  const own = data ?? (key ? cache.data.get(key) ?? null : null);
  return {
    ownership: own,
    available: classic,
    loading: enabled && classic && Boolean(key) && !own && !error,
    error,
  };
}
