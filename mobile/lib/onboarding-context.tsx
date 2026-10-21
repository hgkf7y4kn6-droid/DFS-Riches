import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { track } from '@/lib/analytics';

const INTRO_KEY = 'dfsriches:intro-seen';
const START_HERE_KEY = 'dfsriches:start-here-hidden';

interface OnboardingValue {
  /** The 3-screen intro is showing. */
  introOpen: boolean;
  showIntro: () => void;
  /** Close the intro; `completed` when the last screen's button was tapped (vs skipped). */
  closeIntro: (completed: boolean) => void;
  /** The user hid Home's "Start here" card. */
  startHereHidden: boolean;
  setStartHereHidden: (hidden: boolean) => void;
}

const OnboardingContext = createContext<OnboardingValue | null>(null);

/**
 * First-run help: the intro shown the first time the app opens (re-opened
 * from Settings) and Home's "Start here" card. Both are remembered on the
 * device.
 */
export function OnboardingProvider({ children }: { children: ReactNode }) {
  const [introOpen, setIntroOpen] = useState(false);
  const [startHereHidden, setHidden] = useState(false);

  useEffect(() => {
    AsyncStorage.multiGet([INTRO_KEY, START_HERE_KEY])
      .then(([[, seen], [, hidden]]) => {
        if (!seen) setIntroOpen(true);
        setHidden(hidden === '1');
      })
      .catch(() => {});
  }, []);

  const showIntro = useCallback(() => setIntroOpen(true), []);
  const closeIntro = useCallback((completed: boolean) => {
    track(completed ? 'intro_completed' : 'intro_skipped');
    setIntroOpen(false);
    AsyncStorage.setItem(INTRO_KEY, '1').catch(() => {});
  }, []);
  const setStartHereHidden = useCallback((hidden: boolean) => {
    track(hidden ? 'start_here_hidden' : 'start_here_shown');
    setHidden(hidden);
    AsyncStorage.setItem(START_HERE_KEY, hidden ? '1' : '0').catch(() => {});
  }, []);

  const value = useMemo(
    () => ({ introOpen, showIntro, closeIntro, startHereHidden, setStartHereHidden }),
    [introOpen, showIntro, closeIntro, startHereHidden, setStartHereHidden],
  );
  return <OnboardingContext.Provider value={value}>{children}</OnboardingContext.Provider>;
}

export function useOnboarding(): OnboardingValue {
  const ctx = useContext(OnboardingContext);
  if (!ctx) throw new Error('useOnboarding must be used inside <OnboardingProvider>');
  return ctx;
}
