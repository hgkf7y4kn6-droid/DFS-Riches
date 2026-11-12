import { getGameDetail } from '@/lib/api';
import { createFetchCache, useCachedFetch } from '@/lib/cached-fetch';
import { useWeek } from '@/lib/week-context';

const cache = createFetchCache<GameDetail>();

/** One game's Weekly Breakdown (/api/breakdown/game/{id}), loaded once per game per session. */
export function useGameDetail(gameId: string | null): { detail: GameDetail | null; error: string | null } {
  const { season, week } = useWeek();
  const key = gameId && season && week ? gameId : '';
  const { data, error } = useCachedFetch(cache, key, () => getGameDetail(season!, week!, gameId!));
  return { detail: data, error };
}
