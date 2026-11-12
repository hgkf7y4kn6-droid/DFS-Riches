import { getPlays } from '@/lib/api';
import { createFetchCache, useCachedFetch } from '@/lib/cached-fetch';
import { useDfsModel } from '@/lib/dfs-model-context';
import { useWeek } from '@/lib/week-context';

const cache = createFetchCache<PlaysResponse>();

/** Cash or GPP plays for the slate picked in the DFS model tabs; pull-to-refresh via refresh(). */
export function usePlays(contest: PlayContest, enabled = true) {
  const { season, week } = useWeek();
  const { slateId } = useDfsModel();
  const key = enabled && season && week ? `${season}:${week}:${slateId ?? 'default'}:${contest}` : '';
  return useCachedFetch(cache, key, () => getPlays(season!, week!, contest, slateId));
}
