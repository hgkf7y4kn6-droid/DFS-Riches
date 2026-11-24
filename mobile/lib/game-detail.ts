import { getGameDetail } from '@/lib/api';
import { createFetchCache, useCachedFetch } from '@/lib/cached-fetch';
import { useWeek } from '@/lib/week-context';

const cache = createFetchCache<GameDetail>();

/** One game's Weekly Breakdown (/api/breakdown/game/{id}), loaded once per game (and slate) per session. */
export function useGameDetail(gameId: string | null, slateId?: string | null): { detail: GameDetail | null; error: string | null } {
  const { season, week } = useWeek();
  const key = gameId && season && week ? `${gameId}|${slateId ?? ''}` : '';
  const { data, error } = useCachedFetch(cache, key, () => getGameDetail(season!, week!, gameId!, slateId));
  return { detail: data, error };
}
