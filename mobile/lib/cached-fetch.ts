import { useCallback, useEffect, useEffectEvent, useState } from 'react';

/** Session cache for one kind of response: results by key, plus requests in flight. */
export interface FetchCache<T> {
  data: Map<string, T>;
  pending: Map<string, Promise<T>>;
}

export const createFetchCache = <T,>(): FetchCache<T> => ({ data: new Map(), pending: new Map() });

/**
 * Loads `key` once per session (shared by every component asking for it, and
 * by requests already in flight); refresh() fetches it again. An empty key
 * means "nothing to load yet".
 */
export function useCachedFetch<T>(cache: FetchCache<T>, key: string, load: () => Promise<T>) {
  // Held in state (not only read from the module cache) so React re-renders --
  // the React Compiler memoizes plain reads of module-level data.
  const [fetched, setFetched] = useState<{ key: string; data: T } | null>(null);
  const [error, setError] = useState<{ key: string; message: string } | null>(null);
  const [nonce, setNonce] = useState(0);
  const data = key ? (fetched?.key === key ? fetched.data : cache.data.get(key) ?? null) : null;
  const fetchNow = useEffectEvent(load);

  useEffect(() => {
    if (!key || (cache.data.has(key) && nonce === 0)) return;
    let cancelled = false;
    let request = nonce === 0 ? cache.pending.get(key) : undefined;
    if (!request) {
      const p = fetchNow();
      request = p;
      cache.pending.set(key, p);
      p.catch(() => {}).finally(() => cache.pending.get(key) === p && cache.pending.delete(key));
    }
    request
      .then((d) => {
        cache.data.set(key, d);
        if (!cancelled) setFetched({ key, data: d });
      })
      .catch((e) => !cancelled && setError({ key, message: e instanceof Error ? e.message : String(e) }))
      .finally(() => !cancelled && setNonce(0));
    return () => {
      cancelled = true;
    };
  }, [cache, key, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  const err = error?.key === key ? error.message : null;
  return { data, error: err, loading: Boolean(key) && !data && !err, refreshing: nonce > 0, refresh };
}
