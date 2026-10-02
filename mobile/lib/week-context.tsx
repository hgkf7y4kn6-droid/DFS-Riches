import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { getNflState, getOptimal, getSlatePlayers, getWeek } from '@/lib/api';
import { emptyLineup } from '@/lib/lineups';
import { MAX_LINEUPS } from '@/constants/config';

interface Loadable<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

interface WeekContextValue {
  season: number | null;
  week: number | null;
  weekData: Loadable<WeekData>;
  refresh: () => Promise<void>;
  /** The slate expanded on Home / shown on Lineups. */
  selectedSlate: Slate | null;
  selectSlate: (slateId: string) => void;
  optimal: Loadable<OptimalResponse>;
  players: Loadable<SlatePlayers>;
  /** Builder lineups for the selected slate (kept per slate for the session). */
  lineups: BuilderLineup[];
  activeLineup: number;
  setActiveLineup: (i: number) => void;
  setLineup: (i: number, lineup: BuilderLineup) => void;
  addLineup: () => void;
  deleteLineup: (i: number) => void;
  /** Saves the selected slate's lineups on the device; they're restored next time the slate opens. */
  saveLineups: () => void;
  /** When the selected slate's lineups were last saved (ISO), or null. */
  savedAt: string | null;
  /** True when the lineups differ from what was last saved. */
  unsaved: boolean;
}

const SAVED_KEY = 'dfsriches:saved-lineups:v1';

/** Saved lineups for one slate: draftable ids per slot (null = open slot). */
interface SavedSlateLineups {
  active: number;
  lineups: (number | null)[][];
  savedAt: string;
}

const toIds = (lineups: BuilderLineup[]) => lineups.map((lu) => lu.map((p) => p?.dk_draftable_id ?? null));

const WeekContext = createContext<WeekContextValue | null>(null);

const idle = <T,>(): Loadable<T> => ({ data: null, loading: false, error: null });
const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** The first slate worth showing: Classic Sunday Main, else the first one with salaries. */
function defaultSlate(slates: Slate[]): Slate | null {
  return slates.find((s) => s.slate_id === 'classic_sunday' && s.available) ?? slates.find((s) => s.available) ?? slates[0] ?? null;
}

export function WeekProvider({ children }: { children: ReactNode }) {
  const [season, setSeason] = useState<number | null>(null);
  const [week, setWeek] = useState<number | null>(null);
  const [weekData, setWeekData] = useState<Loadable<WeekData>>({ data: null, loading: true, error: null });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [optimal, setOptimal] = useState<Loadable<OptimalResponse>>(idle);
  const [players, setPlayers] = useState<Loadable<SlatePlayers>>(idle);
  const [builder, setBuilder] = useState<Record<string, { lineups: BuilderLineup[]; active: number }>>({});
  const [saved, setSaved] = useState<Record<string, SavedSlateLineups>>({});

  useEffect(() => {
    AsyncStorage.getItem(SAVED_KEY)
      .then((raw) => raw && setSaved(JSON.parse(raw)))
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setWeekData((s) => ({ ...s, loading: true, error: null }));
    try {
      const state = await getNflState();
      const szn = Number(state.season);
      const wk = state.season_type === 'pre' ? 1 : Math.max(1, Math.min(18, Number(state.display_week ?? state.week)));
      const data = await getWeek(szn, wk);
      setSeason(szn);
      setWeek(wk);
      setWeekData({ data, loading: false, error: null });
      setSelectedId((cur) => (cur && data.slates.some((s) => s.slate_id === cur) ? cur : defaultSlate(data.slates)?.slate_id ?? null));
    } catch (e) {
      setWeekData((s) => ({ ...s, loading: false, error: message(e) }));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const selectedSlate = useMemo(
    () => weekData.data?.slates.find((s) => s.slate_id === selectedId) ?? null,
    [weekData.data, selectedId],
  );

  // Optimal lineups and the player pool for the selected slate.
  useEffect(() => {
    if (!season || !week || !selectedSlate) return;
    let cancelled = false;
    const id = selectedSlate.slate_id;
    setOptimal({ data: null, loading: true, error: null });
    setPlayers({ data: null, loading: selectedSlate.available, error: null });
    getOptimal(season, week, id)
      .then((data) => !cancelled && setOptimal({ data, loading: false, error: null }))
      .catch((e) => !cancelled && setOptimal({ data: null, loading: false, error: message(e) }));
    if (selectedSlate.available) {
      getSlatePlayers(season, week, id)
        .then((data) => !cancelled && setPlayers({ data, loading: false, error: null }))
        .catch((e) => !cancelled && setPlayers({ data: null, loading: false, error: message(e) }));
    }
    return () => {
      cancelled = true;
    };
  }, [season, week, selectedSlate]);

  const slateKey = selectedSlate?.slate_id ?? '';
  // Saved lineups are per season/week/slate.
  const savedKey = season && week && slateKey ? `${season}:${week}:${slateKey}` : '';
  const slateType = selectedSlate?.slate_type ?? 'classic';

  // First time a slate's player pool loads this session, restore its saved lineups.
  useEffect(() => {
    const pool = players.data?.players;
    const entry = saved[savedKey];
    if (!pool || !entry || builder[slateKey] || players.data?.slate.slate_id !== slateKey) return;
    const byId = new Map(pool.map((p) => [p.dk_draftable_id, p]));
    const size = emptyLineup(slateType).length;
    const lineups = entry.lineups
      .filter((ids) => ids.length === size)
      .slice(0, MAX_LINEUPS)
      .map((ids) => ids.map((id) => (id == null ? null : byId.get(id) ?? null)));
    if (lineups.length) {
      setBuilder((all) => ({ ...all, [slateKey]: { lineups, active: Math.min(entry.active, lineups.length - 1) } }));
    }
  }, [players.data, saved, savedKey, slateKey, slateType, builder]);

  const current = builder[slateKey] ?? { lineups: [emptyLineup(slateType)], active: 0 };
  const savedEntry = saved[savedKey];

  const update = useCallback(
    (fn: (cur: { lineups: BuilderLineup[]; active: number }) => { lineups: BuilderLineup[]; active: number }) => {
      if (!slateKey) return;
      setBuilder((all) => ({ ...all, [slateKey]: fn(all[slateKey] ?? { lineups: [emptyLineup(slateType)], active: 0 }) }));
    },
    [slateKey, slateType],
  );

  const value: WeekContextValue = {
    season,
    week,
    weekData,
    refresh: load,
    selectedSlate,
    selectSlate: setSelectedId,
    optimal,
    players,
    lineups: current.lineups,
    activeLineup: current.active,
    setActiveLineup: (i) => update((c) => ({ ...c, active: i })),
    setLineup: (i, lineup) => update((c) => ({ ...c, lineups: c.lineups.map((l, j) => (j === i ? lineup : l)) })),
    addLineup: () =>
      update((c) =>
        c.lineups.length >= MAX_LINEUPS ? c : { lineups: [...c.lineups, emptyLineup(slateType)], active: c.lineups.length },
      ),
    deleteLineup: (i) =>
      update((c) => {
        const lineups = c.lineups.filter((_, j) => j !== i);
        return lineups.length
          ? { lineups, active: Math.min(c.active, lineups.length - 1) }
          : { lineups: [emptyLineup(slateType)], active: 0 };
      }),
    saveLineups: () => {
      if (!savedKey) return;
      const entry: SavedSlateLineups = { active: current.active, lineups: toIds(current.lineups), savedAt: new Date().toISOString() };
      setSaved((all) => {
        const next = { ...all, [savedKey]: entry };
        AsyncStorage.setItem(SAVED_KEY, JSON.stringify(next)).catch(() => {});
        return next;
      });
    },
    savedAt: savedEntry?.savedAt ?? null,
    unsaved: JSON.stringify(toIds(current.lineups)) !== JSON.stringify(savedEntry?.lineups ?? toIds([emptyLineup(slateType)])),
  };

  return <WeekContext.Provider value={value}>{children}</WeekContext.Provider>;
}

export function useWeek(): WeekContextValue {
  const ctx = useContext(WeekContext);
  if (!ctx) throw new Error('useWeek must be used inside <WeekProvider>');
  return ctx;
}
