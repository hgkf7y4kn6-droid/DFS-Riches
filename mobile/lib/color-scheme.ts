import { useSyncExternalStore } from 'react';
import { useColorScheme as useSystemColorScheme } from 'react-native';

const noSubscription = () => () => {};

/**
 * The device's light / dark setting, safe for the pre-rendered web pages: those
 * are rendered as light, and React keeps pre-rendered inline styles while
 * hydrating, so the hydrating render matches (light) and the next one switches
 * to the device's theme. Native, and anything mounted later, get it right away.
 */
export function useColorScheme() {
  const scheme = useSystemColorScheme();
  const hydrated = useSyncExternalStore(noSubscription, () => true, () => false);
  return hydrated ? scheme : 'light';
}
