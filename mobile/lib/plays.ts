import { useCallback, useEffect, useState } from 'react';

import { getPlays } from '@/lib/api';
import { useDfsModel } from '@/lib/dfs-model-context';
import { useWeek } from '@/lib/week-context';

// One response per season/week/slate/contest for the session.
const cache = new Map<string, PlaysResponse>();

/** Cash or GPP plays for the slate picked in the DFS model tabs; pull-to-refresh via refresh(). */
export function usePlays(contest: PlayContest) {
  const { season, week } = useWeek();
  const { slateId } = useDfsModel();
  const key = season && week ? `${season}:${week}:${slateId ?? 'default'}:${contest}` : '';
  // Held in state so React re-renders (the React Compiler memoizes plain module-cache reads).
  const [fetched, setFetched] = useState<{ key: string; data: PlaysResponse } | null>(null);
  const [error, setError] = useState<{ key: string; message: string } | null>(null);
  const [nonce, setNonce] = useState(0);
  const data = key ? (fetched?.key === key ? fetched.data : cache.get(key) ?? null) : null;

  useEffect(() => {
    if (!key || !season || !week || (cache.has(key) && nonce === 0)) return;
    let cancelled = false;
    getPlays(season, week, contest, slateId)
      .then((d) => {
        cache.set(key, d);
        if (!cancelled) setFetched({ key, data: d });
      })
      .catch((e) => !cancelled && setError({ key, message: e instanceof Error ? e.message : String(e) }))
      .finally(() => !cancelled && setNonce(0));
    return () => {
      cancelled = true;
    };
  }, [key, season, week, contest, slateId, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  const err = error?.key === key ? error.message : null;
  return { data, loading: Boolean(key) && !data && !err, refreshing: nonce > 0, error: err, refresh };
}
