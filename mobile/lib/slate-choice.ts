import { useCallback } from 'react';

import { useDfsModel } from '@/lib/dfs-model-context';
import { usePrefs } from '@/lib/prefs-context';
import { useWeek } from '@/lib/week-context';

/**
 * Pick a slate everywhere at once: the lineup builder / optimal lineups
 * (week context) and, for a Classic slate with salaries, the DFS model behind
 * DFS Model, Safe Plays and Tournaments -- so the header shows the same slate
 * on every tab. The choice is remembered on the account (prefs.lastSlate).
 */
export function useChooseSlate() {
  const { season, week, weekData, selectSlate } = useWeek();
  const { selectSlate: selectModelSlate } = useDfsModel();
  const { update } = usePrefs();
  const slates = weekData.data?.slates;
  return useCallback(
    (id: string, remember = true) => {
      const slate = slates?.find((s) => s.slate_id === id);
      if (slate) selectSlate(id);
      if (!slate || (slate.slate_type === 'classic' && slate.available)) selectModelSlate(id);
      if (remember && season && week) update({ lastSlate: `${season}:${week}:${id}` });
    },
    [slates, selectSlate, selectModelSlate, update, season, week],
  );
}
