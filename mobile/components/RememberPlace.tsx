import { router, usePathname } from 'expo-router';
import { useEffect, useRef } from 'react';

import { tabs } from '@/constants/data';
import { usePrefs } from '@/lib/prefs-context';
import { useChooseSlate } from '@/lib/slate-choice';
import { useWeek } from '@/lib/week-context';

const TAB_PATHS = new Set(tabs.map((t) => (t.name === 'index' ? '/' : `/${t.name}`)));

/**
 * Picks up where the user left off, on any device: the slate they last chose
 * (when it's this week's) and, once per launch, the tab they last had open.
 * Records both as they change (lib/prefs-context.tsx).
 */
export default function RememberPlace() {
  const pathname = usePathname();
  const { prefs, settled, update } = usePrefs();
  const { season, week, weekData, selectedSlate } = useWeek();
  const choose = useChooseSlate();
  const restoredSlate = useRef(false);
  const restoredTab = useRef(false);

  useEffect(() => {
    if (restoredSlate.current || !settled || !season || !week || !weekData.data) return;
    restoredSlate.current = true;
    const [s, w, id] = (prefs.lastSlate ?? '').split(':');
    if (Number(s) === season && Number(w) === week && id && id !== selectedSlate?.slate_id && weekData.data.slates.some((x) => x.slate_id === id)) {
      choose(id, false);
    }
  }, [settled, season, week, weekData.data, prefs.lastSlate, selectedSlate?.slate_id, choose]);

  useEffect(() => {
    if (restoredTab.current || !settled) return;
    restoredTab.current = true;
    if (pathname === '/' && prefs.lastTab && prefs.lastTab !== '/' && TAB_PATHS.has(prefs.lastTab)) router.navigate(prefs.lastTab as never);
  }, [settled, pathname, prefs.lastTab]);

  useEffect(() => {
    if (restoredTab.current && TAB_PATHS.has(pathname) && pathname !== prefs.lastTab) update({ lastTab: pathname });
  }, [pathname, prefs.lastTab, update]);

  return null;
}
