import { getPlayerGames } from '@/lib/api';
import { createFetchCache, useCachedFetch } from '@/lib/cached-fetch';
import { useWeek } from '@/lib/week-context';

const cache = createFetchCache<PlayerGamesResponse>();

/** A player's recent game log (/api/player-games), loaded the first time their card is expanded. */
export function usePlayerGames(player: { name: string; position: string; team: string } | null) {
  const { season, week } = useWeek();
  const key = player && season && week ? `${season}:${week}:${player.name}|${player.position}|${player.team}` : '';
  const { data, loading, error } = useCachedFetch(cache, key, () => getPlayerGames(season!, week!, player!));
  return { data, loading, error };
}
