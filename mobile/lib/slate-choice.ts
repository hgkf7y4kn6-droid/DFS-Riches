import { useCallback } from 'react';

import { useDfsModel } from '@/lib/dfs-model-context';
import { useWeek } from '@/lib/week-context';

/**
 * Pick a slate everywhere at once: the lineup builder / optimal lineups
 * (week context) and, for a Classic slate with salaries, the DFS model behind
 * DFS Model, Safe Plays and Tournaments -- so the header shows the same slate
 * on every tab.
 */
export function useChooseSlate() {
  const { weekData, selectSlate } = useWeek();
  const { selectSlate: selectModelSlate } = useDfsModel();
  const slates = weekData.data?.slates;
  return useCallback(
    (id: string) => {
      const slate = slates?.find((s) => s.slate_id === id);
      if (slate) selectSlate(id);
      if (!slate || (slate.slate_type === 'classic' && slate.available)) selectModelSlate(id);
    },
    [slates, selectSlate, selectModelSlate],
  );
}
