import * as Updates from 'expo-updates';
import { useEffect } from 'react';
import { AppState, Platform } from 'react-native';

// Checks at most this often when the app comes back to the foreground.
const MIN_CHECK_MS = 10 * 60 * 1000;

/**
 * Over-the-air updates (EAS Update) for installed builds. expo-updates already
 * checks on each cold start and applies what it downloads on the next one; this
 * also checks when the app returns from the background and restarts into a new
 * update right away, so a phone that keeps the app open picks up pushes too.
 * Does nothing on the web, in Expo Go or in development.
 */
export function useAppUpdates() {
  useEffect(() => {
    if (Platform.OS === 'web' || __DEV__ || !Updates.isEnabled) return;
    let last = Date.now();
    let busy = false;
    const sub = AppState.addEventListener('change', async (state) => {
      if (state !== 'active' || busy || Date.now() - last < MIN_CHECK_MS) return;
      busy = true;
      last = Date.now();
      try {
        const { isAvailable } = await Updates.checkForUpdateAsync();
        if (isAvailable && (await Updates.fetchUpdateAsync()).isNew) await Updates.reloadAsync();
      } catch {
        // offline or the update server is unreachable: try again next time
      } finally {
        busy = false;
      }
    });
    return () => sub.remove();
  }, []);
}
