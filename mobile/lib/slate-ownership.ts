import { useEffect, useState } from 'react';

import { getDfsModel } from '@/lib/api';
import { useWeek } from '@/lib/week-context';

// DK draftable id -> expected ownership (%), per season:week:slate, for the session.
const cache = new Map<string, Map<number, number>>();

/**
 * The DFS model's expected ownership for a Classic slate, keyed by DraftKings
 * draftable id -- for sorting the lineup builder. Loaded only when `enabled`
 * (the model is a heavy request); Showdown slates have no model, so null.
 */
export function useSlateOwnership(slate: Slate | null, enabled: boolean) {
  const { season, week } = useWeek();
  const classic = slate?.slate_type === 'classic';
  const key = slate && classic && season && week ? `${season}:${week}:${slate.slate_id}` : '';
  // Held in state so React re-renders (the React Compiler memoizes plain module-cache reads).
  const [fetched, setFetched] = useState<{ key: string; own: Map<number, number> } | null>(null);
  const [error, setError] = useState<{ key: string; message: string } | null>(null);
  const own = key ? (fetched?.key === key ? fetched.own : cache.get(key) ?? null) : null;

  useEffect(() => {
    if (!enabled || !key || !slate || !season || !week || cache.has(key)) return;
    let cancelled = false;
    getDfsModel(season, week, slate.slate_id)
      .then((m) => {
        const map = new Map<number, number>();
        for (const p of m.table ?? []) if (p.ownership != null) map.set(p.id, p.ownership);
        cache.set(key, map);
        if (!cancelled) setFetched({ key, own: map });
      })
      .catch((e) => !cancelled && setError({ key, message: e instanceof Error ? e.message : String(e) }));
    return () => {
      cancelled = true;
    };
    // slate is identified by key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, key, season, week]);

  return {
    ownership: own,
    available: classic,
    loading: enabled && classic && Boolean(key) && !own && error?.key !== key,
    error: error?.key === key ? error.message : null,
  };
}
