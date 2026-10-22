import { useEffect, useState } from 'react';
import { Modal, Pressable, ScrollView, Text, View } from 'react-native';

import { track } from '@/lib/analytics';
import { useOnboarding } from '@/lib/onboarding-context';

const PAGES: { kicker: string; title: string; body: string[] }[] = [
  {
    kicker: 'Welcome',
    title: 'Smarter DraftKings NFL lineups',
    body: [
      'DFSRiches projects every player on each DraftKings slate from a blend of projection sources, adjusted for matchups, Vegas lines and the weather.',
      'Each week comes down to three steps: pick a slate, see the top plays, build your lineups. Home walks you through them.',
    ],
  },
  {
    kicker: 'Two kinds of contests',
    title: 'Safe Plays vs Tournaments',
    body: [
      'Cash games (50/50s, double-ups, head-to-heads) pay about half the field. You just need a steady score, so the Safe Plays tab picks players with a high floor.',
      'Tournaments (GPPs) pay the top finishers, with the big money at the very top. You need upside and a lineup the field doesn\'t have, so the Tournaments tab picks big ceilings the crowd is overlooking.',
    ],
  },
  {
    kicker: 'Your first lineup',
    title: 'Build a lineup',
    body: [
      'Open the Lineups tab, pick a slate and tap players to add them. Lineups have to fit under the $50,000 salary cap, and players who no longer fit are dimmed with the reason.',
      'Start from a model lineup (Safe or Tournament) if you like. Your saved lineups sync to your account.',
      'Tap any word with a dotted underline to see what it means. The full glossary is in Settings (the gear at the top).',
    ],
  },
];

/** The 3-screen intro: shown the first time the app opens, and from Settings. Skippable. */
export default function IntroTour() {
  const { introOpen, closeIntro } = useOnboarding();
  const [page, setPage] = useState(0);
  const last = page === PAGES.length - 1;
  // Counted when it's actually on screen (it waits for sign-in behind the tabs).
  useEffect(() => {
    if (introOpen) track('intro_shown');
  }, [introOpen]);
  const p = PAGES[page];
  const close = (completed: boolean) => {
    closeIntro(completed);
    setPage(0);
  };

  return (
    <Modal visible={introOpen} transparent animationType="fade" onRequestClose={() => close(false)}>
      <View className="week-backdrop">
        <View className="week-sheet intro-sheet">
          <View className="flex-row items-center justify-between">
            <Text className="intro-kicker">
              {p.kicker} · {page + 1} of {PAGES.length}
            </Text>
            {!last ? (
              <Pressable onPress={() => close(false)} accessibilityRole="button" hitSlop={10}>
                <Text className="caption">Skip</Text>
              </Pressable>
            ) : null}
          </View>
          <ScrollView style={{ maxHeight: 420 }}>
            <Text className="intro-title">{p.title}</Text>
            {p.body.map((line, i) => (
              <Text key={i} className="intro-text">
                {line}
              </Text>
            ))}
          </ScrollView>
          <View className="intro-dots">
            {PAGES.map((_, i) => (
              <View key={i} className={`intro-dot ${i === page ? 'intro-dot-active' : ''}`} />
            ))}
          </View>
          <View className="flex-row gap-2">
            {page > 0 ? (
              <Pressable className="btn-outline flex-1 justify-center" onPress={() => setPage(page - 1)} accessibilityRole="button">
                <Text className="btn-outline-text">Back</Text>
              </Pressable>
            ) : null}
            <Pressable
              className="btn flex-1"
              onPress={() => {
                if (last) return close(true);
                track('intro_page', { page: page + 2 });
                setPage(page + 1);
              }}
              accessibilityRole="button">
              <Text className="btn-text">{last ? 'Get started' : 'Next'}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}
