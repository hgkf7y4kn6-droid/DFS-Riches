import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { useAccountSync, useSyncedDoc } from '@/lib/account-sync';
import { track } from '@/lib/analytics';

const STORAGE_KEY = 'dfsriches:prefs:v1';

/** What the user plays (asked once after sign-up). */
export type ContestFocus = 'cash' | 'gpp' | 'both';
/** Roughly how much they enter per week. */
export type WeeklySpend = 'free' | 'under25' | '25-100' | '100-500' | 'over500';

export interface Prefs {
  focus?: ContestFocus;
  spend?: WeeklySpend;
  /** "season:week:slateId": the slate they last picked. */
  lastSlate?: string;
  /** The tab they last opened (a route like "/cash"). */
  lastTab?: string;
  /** The lineup builder's sorts and their weights. */
  builder?: { selected: string[]; weights: Record<string, number> };
  /** When the "What do you play?" question was answered or dismissed. */
  askedAt?: string;
}

export const FOCUS_OPTIONS: { id: ContestFocus; label: string; hint: string }[] = [
  { id: 'cash', label: 'Cash games', hint: '50/50s, double-ups, head-to-heads' },
  { id: 'gpp', label: 'Tournaments', hint: 'GPPs with big top prizes' },
  { id: 'both', label: 'Both', hint: 'A mix of each' },
];

export const SPEND_OPTIONS: { id: WeeklySpend; label: string }[] = [
  { id: 'free', label: 'Free contests only' },
  { id: 'under25', label: 'Under $25' },
  { id: '25-100', label: '$25–$100' },
  { id: '100-500', label: '$100–$500' },
  { id: 'over500', label: '$500+' },
];

/** Best Contests' entry-fee groups (app.contests FEE_GROUPS) that fit a weekly budget. */
export const FEES_FOR_SPEND: Record<WeeklySpend, string[]> = {
  free: ['under1'],
  under25: ['under1', '1-5'],
  '25-100': ['1-5', '6-10'],
  '100-500': ['6-10', '11-25'],
  over500: ['11-25', 'over25'],
};

/** Where "See the top plays" goes for each focus. */
export const PLAYS_ROUTE: Record<ContestFocus, '/cash' | '/gpp' | '/dfs-model'> = { cash: '/cash', gpp: '/gpp', both: '/dfs-model' };

interface PrefsValue {
  prefs: Prefs;
  /** Read from the device (and, signed in, the account) -- don't act on prefs before this. */
  loaded: boolean;
  /** The account's copy has been merged in (so "not answered yet" is real, not just this device). */
  settled: boolean;
  /** The "What do you play?" question was answered or dismissed (here or on another device). */
  asked: boolean;
  update: (patch: Partial<Prefs>) => void;
}

const PrefsContext = createContext<PrefsValue | null>(null);

/**
 * The user's preferences and "where I left off" (contest focus, weekly
 * budget, last slate and tab, builder sorts), saved on the device and synced
 * to the account as the "prefs" document, so they follow the user to every
 * device.
 */
export function PrefsProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<Prefs>({});
  const [loaded, setLoaded] = useState(false);
  const { status, remote } = useAccountSync();

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((raw) => raw && setPrefs(JSON.parse(raw)))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  const save = useCallback((next: Prefs) => {
    setPrefs(next);
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(next)).catch(() => {});
  }, []);

  // The account copy wins field by field once this device has synced (lib/account-sync.tsx).
  useSyncedDoc<Prefs>('prefs', prefs, loaded, (v) => save(v ?? {}), (local, remoteValue) => ({ ...local, ...(remoteValue ?? {}) }));

  const update = useCallback(
    (patch: Partial<Prefs>) => {
      setPrefs((cur) => {
        const next = { ...cur, ...patch };
        AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(next)).catch(() => {});
        if (patch.focus && patch.focus !== cur.focus) track('prefs_focus_set', { focus: patch.focus });
        if (patch.spend && patch.spend !== cur.spend) track('prefs_spend_set', { spend: patch.spend });
        return next;
      });
    },
    [],
  );

  // Settled once the account's copy is in (or sync can't run: no storage, an error).
  const settled = loaded && (status === 'offline' || status === 'error' || (remote != null && (status === 'synced' || status === 'saving')));
  const asked = Boolean(prefs.askedAt || (remote?.prefs?.value as Prefs | undefined)?.askedAt);
  const value = useMemo(() => ({ prefs, loaded, settled, asked, update }), [prefs, loaded, settled, asked, update]);
  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs(): PrefsValue {
  const ctx = useContext(PrefsContext);
  if (!ctx) throw new Error('usePrefs must be used inside <PrefsProvider>');
  return ctx;
}
