import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { useSyncedDoc } from '@/lib/account-sync';

const STORAGE_KEY = 'dfsriches:pool-tags:v1';

interface PoolTagsValue {
  /** pool key -> the user's tags in that pool. */
  pools: Record<string, PoolTags>;
  setTag: (pool: string, playerId: number, tag: PlayTag | null) => void;
  resetPool: (pool: string) => void;
  clearAll: () => void;
}

const PoolTagsContext = createContext<PoolTagsValue | null>(null);

/** One pool per season, week, slate and contest type (cash and GPP pools are kept apart). */
export const poolKey = (season: number, week: number, slateId: string, contest: PlayContest) =>
  `${season}:${week}:${slateId}:${contest}`;

/**
 * The user's own Prioritize / Neutral / Fade calls, overriding the model's
 * tags player by player. Saved on the device.
 */
export function PoolTagsProvider({ children }: { children: ReactNode }) {
  const [pools, setPools] = useState<Record<string, PoolTags>>({});
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((raw) => raw && setPools(JSON.parse(raw)))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  const update = useCallback((fn: (all: Record<string, PoolTags>) => Record<string, PoolTags>) => {
    setPools((all) => {
      const next = fn(all);
      AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(next)).catch(() => {});
      return next;
    });
  }, []);

  useSyncedDoc<Record<string, PoolTags>>('pool_tags', pools, loaded, (v) => update(() => v), (local, remote) => {
    const out: Record<string, PoolTags> = { ...(remote ?? {}) };
    for (const [pool, tags] of Object.entries(local)) out[pool] = { ...(out[pool] ?? {}), ...tags };
    return out;
  });

  const value = useMemo<PoolTagsValue>(
    () => ({
      pools,
      setTag: (pool, playerId, tag) =>
        update((all) => {
          const current = { ...(all[pool] ?? {}) };
          if (tag) current[playerId] = tag;
          else delete current[playerId];
          return { ...all, [pool]: current };
        }),
      resetPool: (pool) =>
        update((all) => {
          const { [pool]: _removed, ...rest } = all;
          return rest;
        }),
      clearAll: () => {
        setPools({});
        AsyncStorage.removeItem(STORAGE_KEY).catch(() => {});
      },
    }),
    [pools, update],
  );

  return <PoolTagsContext.Provider value={value}>{children}</PoolTagsContext.Provider>;
}

export function usePoolTags() {
  const ctx = useContext(PoolTagsContext);
  if (!ctx) throw new Error('usePoolTags must be used inside PoolTagsProvider');
  return ctx;
}

export type Pool = ReturnType<typeof usePool>;

/** The user's tags for one pool, plus each player's effective tag (the user's call, else the model's). */
export function usePool(pool: string | null) {
  const { pools, setTag, resetPool } = usePoolTags();
  const tags = pool ? pools[pool] ?? {} : {};
  return {
    tags,
    tagOf: (p: PlayPlayer): PlayTag => tags[p.id] ?? p.tag,
    isMine: (p: PlayPlayer) => tags[p.id] != null,
    setTag: (p: PlayPlayer, tag: PlayTag) => pool && setTag(pool, p.id, tag === p.tag ? null : tag),
    reset: () => pool && resetPool(pool),
  };
}
