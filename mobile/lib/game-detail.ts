import { useEffect, useState } from 'react';

import { getGameDetail } from '@/lib/api';
import { useWeek } from '@/lib/week-context';

// Game details are fetched once per game per session.
const cache = new Map<string, GameDetail>();

/** One game's Weekly Breakdown (/api/breakdown/game/{id}), loaded on first use. */
export function useGameDetail(gameId: string | null): { detail: GameDetail | null; error: string | null } {
  const { season, week } = useWeek();
  // Held in state (not just read from the module cache) so React re-renders --
  // the React Compiler memoizes plain reads of module-level data.
  const [fetched, setFetched] = useState<{ id: string; detail: GameDetail } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const detail = gameId ? (fetched?.id === gameId ? fetched.detail : cache.get(gameId) ?? null) : null;

  useEffect(() => {
    if (!gameId || !season || !week || cache.has(gameId)) return;
    let cancelled = false;
    getGameDetail(season, week, gameId)
      .then((d) => {
        cache.set(gameId, d);
        if (!cancelled) setFetched({ id: gameId, detail: d });
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [season, week, gameId]);

  return { detail, error };
}
