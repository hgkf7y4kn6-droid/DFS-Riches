import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { useSyncedDoc } from '@/lib/account-sync';
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
  /** The NFL's current season and week (Sleeper), whatever week is being viewed. */
  current: { season: number; week: number } | null;
  /** View another season / week (every tab follows); null returns to the current week. */
  setSeasonWeek: (seasonWeek: { season: number; week: number } | null) => void;
  /** The slate expanded on Home / shown on Lineups. */
  selectedSlate: Slate | null;
  selectSlate: (slateId: string) => void;
  optimal: Loadable<OptimalResponse>;
  players: Loadable<SlatePlayers>;
  /** The lineup builder for the selected slate in one scope (see useLineups). */
  lineupsFor: (scope: LineupScope) => LineupBuilderState;
  /** Deletes every saved lineup on the device and resets the builders. */
  clearSavedLineups: () => void;
}

/** Which builder: the Lineups tab's (''), or the Cash / GPP tabs' own sets. */
export type LineupScope = '' | 'cash' | 'gpp' | 'edit';
// 'edit' (a logged entry open for late swap) is never saved as builder lineups.
const SCOPES: LineupScope[] = ['', 'cash', 'gpp'];

export interface LineupBuilderState {
  /** Builder lineups for the selected slate (kept per slate and scope for the session). */
  lineups: BuilderLineup[];
  activeLineup: number;
  setActiveLineup: (i: number) => void;
  setLineup: (i: number, lineup: BuilderLineup) => void;
  addLineup: () => void;
  deleteLineup: (i: number) => void;
  /** Saves these lineups; they're restored next time the slate opens. */
  saveLineups: () => void;
  /** When these lineups were last saved (ISO), or null. */
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
  const [current, setCurrent] = useState<{ season: number; week: number } | null>(null);
  const [chosen, setChosen] = useState<{ season: number; week: number } | null>(null);
  const [weekData, setWeekData] = useState<Loadable<WeekData>>({ data: null, loading: true, error: null });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [optimal, setOptimal] = useState<Loadable<OptimalResponse>>(idle);
  const [players, setPlayers] = useState<Loadable<SlatePlayers>>(idle);
  const [builder, setBuilder] = useState<Record<string, { lineups: BuilderLineup[]; active: number }>>({});
  const [saved, setSaved] = useState<Record<string, SavedSlateLineups>>({});
  const [savedLoaded, setSavedLoaded] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(SAVED_KEY)
      .then((raw) => raw && setSaved(JSON.parse(raw)))
      .catch(() => {})
      .finally(() => setSavedLoaded(true));
  }, []);

  // Saved lineups follow the signed-in account; a device's first sync keeps the newer save per slate.
  useSyncedDoc<Record<string, SavedSlateLineups>>(
    'saved_lineups',
    saved,
    savedLoaded,
    (v) => {
      setSaved(v ?? {});
      setBuilder({});
      AsyncStorage.setItem(SAVED_KEY, JSON.stringify(v ?? {})).catch(() => {});
    },
    (local, remote) => {
      const out = { ...(remote ?? {}) };
      for (const [k, entry] of Object.entries(local)) if (!out[k] || out[k].savedAt < entry.savedAt) out[k] = entry;
      return out;
    },
  );

  const load = useCallback(async () => {
    setWeekData((s) => ({ ...s, loading: true, error: null }));
    try {
      const state = await getNflState();
      const nowSzn = Number(state.season);
      const nowWk = state.season_type === 'pre' ? 1 : Math.max(1, Math.min(18, Number(state.display_week ?? state.week)));
      setCurrent({ season: nowSzn, week: nowWk });
      const szn = chosen?.season ?? nowSzn;
      const wk = chosen?.week ?? nowWk;
      const data = await getWeek(szn, wk);
      setSeason(szn);
      setWeek(wk);
      setWeekData({ data, loading: false, error: null });
      setSelectedId((cur) => (cur && data.slates.some((s) => s.slate_id === cur) ? cur : defaultSlate(data.slates)?.slate_id ?? null));
    } catch (e) {
      setWeekData((s) => ({ ...s, loading: false, error: message(e) }));
    }
  }, [chosen]);

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
  // Saved lineups are per season/week/slate, plus ":cash" / ":gpp" for the Cash and GPP tabs' sets.
  const baseSavedKey = season && week && slateKey ? `${season}:${week}:${slateKey}` : '';
  const savedKeyFor = (scope: LineupScope) => (baseSavedKey && scope ? `${baseSavedKey}:${scope}` : baseSavedKey);
  // A Cash / GPP set that was never saved starts from the slate's earlier (unscoped) save.
  const savedEntryFor = (scope: LineupScope): SavedSlateLineups | undefined =>
    saved[savedKeyFor(scope)] ?? (scope ? saved[baseSavedKey] : undefined);
  // Builders are per season/week/slate (and scope), so switching weeks never mixes in another week's players.
  const builderKey = (scope: LineupScope) => `${season}:${week}:${slateKey}${scope ? `|${scope}` : ''}`;
  const slateType = selectedSlate?.slate_type ?? 'classic';

  // First time a slate's player pool loads this session, restore each scope's saved lineups.
  useEffect(() => {
    const pool = players.data?.players;
    if (!pool || players.data?.slate.slate_id !== slateKey) return;
    const byId = new Map(pool.map((p) => [p.dk_draftable_id, p]));
    const size = emptyLineup(slateType).length;
    const restored: Record<string, { lineups: BuilderLineup[]; active: number }> = {};
    for (const scope of SCOPES) {
      const entry = savedEntryFor(scope);
      if (!entry || builder[builderKey(scope)]) continue;
      const lineups = entry.lineups
        .filter((ids) => ids.length === size)
        .slice(0, MAX_LINEUPS)
        .map((ids) => ids.map((id) => (id == null ? null : byId.get(id) ?? null)));
      if (lineups.length) restored[builderKey(scope)] = { lineups, active: Math.min(entry.active, lineups.length - 1) };
    }
    if (Object.keys(restored).length) setBuilder((all) => ({ ...all, ...restored }));
    // savedEntryFor / builderKey derive from the listed state
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [players.data, saved, baseSavedKey, slateKey, slateType, builder]);

  const lineupsFor = (scope: LineupScope): LineupBuilderState => {
    const bKey = builderKey(scope);
    const sKey = scope === 'edit' ? '' : savedKeyFor(scope);
    const fresh = () => ({ lineups: [emptyLineup(slateType)], active: 0 });
    const current = builder[bKey] ?? fresh();
    const savedEntry = sKey ? saved[sKey] : undefined;
    const update = (fn: (cur: { lineups: BuilderLineup[]; active: number }) => { lineups: BuilderLineup[]; active: number }) => {
      if (!slateKey) return;
      setBuilder((all) => ({ ...all, [bKey]: fn(all[bKey] ?? fresh()) }));
    };
    return {
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
          return lineups.length ? { lineups, active: Math.min(c.active, lineups.length - 1) } : fresh();
        }),
      saveLineups: () => {
        if (!sKey) return;
        const entry: SavedSlateLineups = { active: current.active, lineups: toIds(current.lineups), savedAt: new Date().toISOString() };
        setSaved((all) => {
          const next = { ...all, [sKey]: entry };
          AsyncStorage.setItem(SAVED_KEY, JSON.stringify(next)).catch(() => {});
          return next;
        });
      },
      savedAt: savedEntry?.savedAt ?? null,
      unsaved: JSON.stringify(toIds(current.lineups)) !== JSON.stringify(savedEntry?.lineups ?? toIds([emptyLineup(slateType)])),
    };
  };

  const value: WeekContextValue = {
    season,
    week,
    weekData,
    refresh: load,
    current,
    setSeasonWeek: (sw) => setChosen(sw && current && sw.season === current.season && sw.week === current.week ? null : sw),
    selectedSlate,
    selectSlate: setSelectedId,
    optimal,
    players,
    lineupsFor,
    clearSavedLineups: () => {
      setSaved({});
      setBuilder({});
      AsyncStorage.removeItem(SAVED_KEY).catch(() => {});
    },
  };

  return <WeekContext.Provider value={value}>{children}</WeekContext.Provider>;
}

/** The lineup builder for the selected slate: the Lineups tab's set (''), or the Cash / GPP tabs' own. */
export function useLineups(scope: LineupScope = ''): LineupBuilderState {
  return useWeek().lineupsFor(scope);
}

export function useWeek(): WeekContextValue {
  const ctx = useContext(WeekContext);
  if (!ctx) throw new Error('useWeek must be used inside <WeekProvider>');
  return ctx;
}
