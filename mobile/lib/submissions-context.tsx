import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

const STORAGE_KEY = 'dfsriches:submissions:v1';

interface SubmissionsContextValue {
  submissions: LineupSubmission[];
  loaded: boolean;
  add: (s: Omit<LineupSubmission, 'id' | 'createdAt'>) => void;
  /** Records a pending entry's winnings (or clears them back to pending with null). */
  settle: (id: string, winnings: number | null) => void;
  remove: (id: string) => void;
  /** Deletes every logged entry. */
  clear: () => void;
}

const SubmissionsContext = createContext<SubmissionsContextValue | null>(null);

/**
 * The user's logged contest entries, newest first, saved on the device with
 * AsyncStorage so the balance card and profit/loss tracker survive restarts.
 */
export function SubmissionsProvider({ children }: { children: ReactNode }) {
  const [submissions, setSubmissions] = useState<LineupSubmission[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((raw) => {
        const parsed = raw ? JSON.parse(raw) : [];
        if (Array.isArray(parsed)) setSubmissions(parsed);
      })
      .catch(() => {
        // unreadable storage: start empty rather than crash
      })
      .finally(() => setLoaded(true));
  }, []);

  const persist = useCallback((fn: (cur: LineupSubmission[]) => LineupSubmission[]) => {
    setSubmissions((cur) => {
      const next = fn(cur);
      AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(next)).catch(() => {});
      return next;
    });
  }, []);

  const value = useMemo<SubmissionsContextValue>(
    () => ({
      submissions,
      loaded,
      add: (s) =>
        persist((cur) => [
          { ...s, id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, createdAt: new Date().toISOString() },
          ...cur,
        ]),
      settle: (id, winnings) => persist((cur) => cur.map((s) => (s.id === id ? { ...s, winnings } : s))),
      remove: (id) => persist((cur) => cur.filter((s) => s.id !== id)),
      clear: () => persist(() => []),
    }),
    [submissions, loaded, persist],
  );

  return <SubmissionsContext.Provider value={value}>{children}</SubmissionsContext.Provider>;
}

export function useSubmissions(): SubmissionsContextValue {
  const ctx = useContext(SubmissionsContext);
  if (!ctx) throw new Error('useSubmissions must be used inside <SubmissionsProvider>');
  return ctx;
}
