import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useState } from 'react';
import { Modal, Pressable, Text, View } from 'react-native';

import { track } from '@/lib/analytics';
import { useOnboarding } from '@/lib/onboarding-context';
import { usePrefs } from '@/lib/prefs-context';
import { useProPicks } from '@/lib/pro-picks-context';

const DISMISSED_KEY = 'dfsriches:pro-picks-reminder-dismissed';

/**
 * After sign-in: reminds Pro users who haven't entered this week's Pro Picks that they can, while it's still
 * open -- once per sign-in (the tabs mount once per signed-in session). Waits for the intro, What's New and
 * the profile question; "Not this week" stops it until next week.
 */
export default function ProPicksReminder() {
  const { state, setEditorOpen } = useProPicks();
  const { introOpen, whatsNewOpen } = useOnboarding();
  const { settled, asked } = usePrefs();
  const [dismissed, setDismissed] = useState<string | null | undefined>(undefined);
  const [show, setShow] = useState(false);
  const [shown, setShown] = useState(false);
  const weekKey = state ? `${state.season}:${state.week}` : null;

  useEffect(() => {
    AsyncStorage.getItem(DISMISSED_KEY)
      .then(setDismissed)
      .catch(() => setDismissed(null));
  }, []);

  const eligible =
    !!state && state.pro && state.status === 'open' && !state.mine && dismissed !== undefined && dismissed !== weekKey;
  // Opened once the other first-run sheets are out of the way (state adjusted during render, React's pattern for it).
  if (!shown && eligible && settled && asked && !introOpen && !whatsNewOpen) {
    setShown(true);
    setShow(true);
  }
  useEffect(() => {
    if (show) track('pro_picks_reminder_shown', {});
  }, [show]);

  const close = (notThisWeek: boolean) => {
    setShow(false);
    if (notThisWeek && weekKey) {
      setDismissed(weekKey);
      AsyncStorage.setItem(DISMISSED_KEY, weekKey).catch(() => {});
    }
    track('pro_picks_reminder_closed', { not_this_week: notThisWeek });
  };

  return (
    <Modal visible={show} transparent animationType="fade" onRequestClose={() => close(false)}>
      <View className="week-backdrop">
        <View className="week-sheet intro-sheet">
          <Text className="intro-kicker">Weekly Pro Picks{state ? ` · Week ${state.week}` : ''}</Text>
          <Text className="intro-title">Think you have this slate figured out?</Text>
          <Text className="intro-text">
            Put your skills to the test by submitting your top-scoring players on this week&apos;s main slate! See how close you can get to perfect and
            where your rankings compare to the other Riches Analytics Pro users!
          </Text>
          <Pressable
            className="btn mt-3"
            onPress={() => {
              close(false);
              setEditorOpen(true);
            }}
            accessibilityRole="button">
            <Text className="btn-text">Make my picks</Text>
          </Pressable>
          <View className="mt-2 flex-row gap-2">
            <Pressable className="btn-outline flex-1 justify-center" onPress={() => close(false)} accessibilityRole="button">
              <Text className="btn-outline-text">Maybe later</Text>
            </Pressable>
            <Pressable className="btn-outline flex-1 justify-center" onPress={() => close(true)} accessibilityRole="button">
              <Text className="btn-outline-text">Not this week</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}
