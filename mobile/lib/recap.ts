import { getRecap } from '@/lib/api';
import { createFetchCache, useCachedFetch } from '@/lib/cached-fetch';
import { useWeek } from '@/lib/week-context';

const cache = createFetchCache<Recap>();

/** The week before the one being viewed, once per session (null in Week 1: nothing has been played). */
export function useRecap(): { recap: Recap | null; error: string | null; loading: boolean; week: number | null } {
  const { season, week } = useWeek();
  const previous = week && week > 1 ? week - 1 : null;
  const key = season && previous ? `${season}:${previous}` : '';
  const { data, error, loading } = useCachedFetch(cache, key, () => getRecap(season!, previous!));
  return { recap: data, error, loading, week: previous };
}
