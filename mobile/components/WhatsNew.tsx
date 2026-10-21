import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import { useEffect, useState } from 'react';
import { Modal, Pressable, Text, View } from 'react-native';

import { WHATS_NEW } from '@/constants/whats-new';
import { useOnboarding } from '@/lib/onboarding-context';

const SEEN_KEY = 'dfsriches:whats-new-seen';
const INTRO_KEY = 'dfsriches:intro-seen';

/**
 * Once per release with a note in constants/whats-new.ts, for people who
 * used the app before it (new users get the intro instead).
 */
export default function WhatsNew() {
  const { introOpen, setWhatsNewOpen } = useOnboarding();
  const version = Constants.expoConfig?.version ?? '';
  const entry = WHATS_NEW.find((e) => e.version === version);
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (!entry) return;
    AsyncStorage.multiGet([SEEN_KEY, INTRO_KEY])
      .then(([[, seen], [, introSeen]]) => {
        if (seen === entry.version) return;
        if (introSeen) {                           // a returning user
          setShow(true);
          setWhatsNewOpen(true);
        }
        else AsyncStorage.setItem(SEEN_KEY, entry.version).catch(() => {});
      })
      .catch(() => {});
  }, [entry, setWhatsNewOpen]);

  const close = () => {
    setShow(false);
    setWhatsNewOpen(false);
    if (entry) AsyncStorage.setItem(SEEN_KEY, entry.version).catch(() => {});
  };

  if (!entry) return null;
  return (
    <Modal visible={show && !introOpen} transparent animationType="fade" onRequestClose={close}>
      <View className="week-backdrop">
        <View className="week-sheet intro-sheet">
          <Text className="intro-kicker">Version {entry.version}</Text>
          <Text className="intro-title">{entry.title}</Text>
          {entry.items.map((item, i) => (
            <Text key={i} className="intro-text">
              • {item}
            </Text>
          ))}
          <Pressable className="btn mt-3" onPress={close} accessibilityRole="button">
            <Text className="btn-text">Got it</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}
