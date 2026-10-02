import { useEffect, useState } from 'react';

import { getPlayerGames } from '@/lib/api';
import { useWeek } from '@/lib/week-context';

// Game logs are fetched once per player per session.
const cache = new Map<string, PlayerGamesResponse>();

/** A player's recent game log (/api/player-games), loaded the first time their card is expanded. */
export function usePlayerGames(player: { name: string; position: string; team: string } | null) {
  const { season, week } = useWeek();
  const key = player && season && week ? `${season}:${week}:${player.name}|${player.position}|${player.team}` : '';
  // Held in state so React re-renders (the React Compiler memoizes plain module-cache reads).
  const [fetched, setFetched] = useState<{ key: string; data: PlayerGamesResponse } | null>(null);
  const [error, setError] = useState<{ key: string; message: string } | null>(null);
  const data = key ? (fetched?.key === key ? fetched.data : cache.get(key) ?? null) : null;

  useEffect(() => {
    if (!key || !player || !season || !week || cache.has(key)) return;
    let cancelled = false;
    getPlayerGames(season, week, player)
      .then((d) => {
        cache.set(key, d);
        if (!cancelled) setFetched({ key, data: d });
      })
      .catch((e) => !cancelled && setError({ key, message: e instanceof Error ? e.message : String(e) }));
    return () => {
      cancelled = true;
    };
    // player is identified by key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, season, week]);

  const err = error?.key === key ? error.message : null;
  return { data, loading: Boolean(key) && !data && !err, error: err };
}
