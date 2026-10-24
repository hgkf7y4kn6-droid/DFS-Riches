import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useState } from 'react';
import { Modal, Pressable, Text, View } from 'react-native';

import { track } from '@/lib/analytics';
import { useOnboarding } from '@/lib/onboarding-context';
import { usePrefs } from '@/lib/prefs-context';
import { flaggedPicks, flaggedText, useProPicks } from '@/lib/pro-picks-context';
import { formatEt } from '@/lib/utils';

const DISMISSED_KEY = 'dfsriches:pro-picks-reminder-dismissed';

/**
 * While this week's Pro Picks are open, after sign-in (the tabs mount once per signed-in session), for Pro users:
 *  - who haven't entered: a reminder that they can;
 *  - whose rankings include a player now listed Out / IR / Doubtful: a prompt to swap him (a player who doesn't
 *    play scores 0). A newly ruled-out player brings it back.
 * Waits for the intro, What's New and the profile question; "Not this week" / "Keep my picks" mutes that reminder.
 */
export default function ProPicksReminder() {
  const { state, setEditorOpen } = useProPicks();
  const { introOpen, whatsNewOpen } = useOnboarding();
  const { settled, asked } = usePrefs();
  const [dismissed, setDismissed] = useState<string | null | undefined>(undefined);
  const [shownKey, setShownKey] = useState<string | null>(null);
  const [show, setShow] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(DISMISSED_KEY)
      .then(setDismissed)
      .catch(() => setDismissed(null));
  }, []);

  const open = !!state && state.pro && state.status === 'open';
  const flagged = open ? flaggedPicks(state, state.mine?.picks) : [];
  const mode: 'enter' | 'ruled_out' | null = !open ? null : !state.mine ? 'enter' : flagged.length ? 'ruled_out' : null;
  const key =
    mode && state
      ? `${state.season}:${state.week}${mode === 'ruled_out' ? `:out:${flagged.map((f) => f.player.id).sort().join(',')}` : ''}`
      : null;
  // Opened once the other first-run sheets are out of the way (state adjusted during render, React's pattern for it).
  if (key && key !== shownKey && dismissed !== undefined && dismissed !== key && settled && asked && !introOpen && !whatsNewOpen) {
    setShownKey(key);
    setShow(true);
  }
  useEffect(() => {
    if (show) track('pro_picks_reminder_shown', { mode: mode ?? 'none' });
  }, [show, mode]);

  const close = (mute: boolean) => {
    setShow(false);
    if (mute && key) {
      setDismissed(key);
      AsyncStorage.setItem(DISMISSED_KEY, key).catch(() => {});
    }
    track('pro_picks_reminder_closed', { mode: mode ?? 'none', muted: mute });
  };

  return (
    <Modal visible={show} transparent animationType="fade" onRequestClose={() => close(false)}>
      <View className="week-backdrop">
        <View className="week-sheet intro-sheet">
          <Text className="intro-kicker">Weekly Pro Picks{state ? ` · Week ${state.week}` : ''}</Text>
          {mode === 'ruled_out' ? (
            <>
              <Text className="intro-title">A player you ranked won&apos;t play</Text>
              <Text className="intro-text">
                {flaggedText(flagged)} {flagged.length === 1 ? 'is' : 'are'} in your Pro Picks. Swap {flagged.length === 1 ? 'him' : 'them'} before the
                Sunday Main locks{state?.lock_at ? ` (${formatEt(state.lock_at)})` : ''}: a ranked player who doesn&apos;t play scores 0.
              </Text>
            </>
          ) : (
            <>
              <Text className="intro-title">Think you have this slate figured out?</Text>
              <Text className="intro-text">
                Put your skills to the test by submitting your top-scoring players on this week&apos;s main slate! See how close you can get to perfect and
                where your rankings compare to the other Riches Analytics Pro users!
              </Text>
            </>
          )}
          <Pressable
            className="btn mt-3"
            onPress={() => {
              close(false);
              setEditorOpen(true);
            }}
            accessibilityRole="button">
            <Text className="btn-text">{mode === 'ruled_out' ? 'Update my picks' : 'Make my picks'}</Text>
          </Pressable>
          <View className="mt-2 flex-row gap-2">
            <Pressable className="btn-outline flex-1 justify-center" onPress={() => close(false)} accessibilityRole="button">
              <Text className="btn-outline-text">Maybe later</Text>
            </Pressable>
            <Pressable className="btn-outline flex-1 justify-center" onPress={() => close(true)} accessibilityRole="button">
              <Text className="btn-outline-text">{mode === 'ruled_out' ? 'Keep my picks' : 'Not this week'}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}
