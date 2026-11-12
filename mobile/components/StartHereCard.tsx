import { router } from 'expo-router';
import type { ReactNode } from 'react';
import { Pressable, Text, View } from 'react-native';

import { SkeletonCards } from '@/components/Skeleton';
import SlateList, { slateTitle } from '@/components/SlateList';
import { Term } from '@/components/Term';
import { track } from '@/lib/analytics';
import { useOnboarding } from '@/lib/onboarding-context';
import { PLAYS_ROUTE, usePrefs } from '@/lib/prefs-context';
import { useChooseSlate } from '@/lib/slate-choice';
import { salariesPendingText } from '@/lib/utils';
import { useWeek } from '@/lib/week-context';

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <View className="start-step">
      <View className="start-step-num">
        <Text className="start-step-num-text">{n}</Text>
      </View>
      <View className="flex-1">
        <Text className="start-step-title">{title}</Text>
        {children}
      </View>
    </View>
  );
}

/**
 * Home's "Start here": 1) pick a slate, 2) see its top plays, 3) build a
 * lineup. Steps 2 and 3 open their screen with the slate from step 1
 * already chosen. Hide it from the card; Settings brings it back.
 */
export default function StartHereCard() {
  const { weekData, selectedSlate } = useWeek();
  const { setStartHereHidden } = useOnboarding();
  const choose = useChooseSlate();
  const slates = weekData.data?.slates ?? [];
  const s = selectedSlate;
  const name = s ? slateTitle(s) : '';
  // Step 2 opens the tab for what they play (lib/prefs-context.tsx).
  const { prefs } = usePrefs();
  const playsRoute = PLAYS_ROUTE[prefs.focus ?? 'both'];
  const playsCopy =
    prefs.focus === 'cash'
      ? { text: 'The safest cash-game plays on this slate, by position.', button: `Safe plays for ${name} ›` }
      : prefs.focus === 'gpp'
        ? { text: 'The best tournament plays on this slate, with ceilings the field is overlooking.', button: `Tournament plays for ${name} ›` }
        : { text: "The model's projections, best values and best games on this slate.", button: `Top plays for ${name} ›` };

  const go = (step: number, path: '/dfs-model' | '/cash' | '/gpp' | '/lineups') => {
    if (!s) return;
    choose(s.slate_id);
    track('start_here_step', { step, slate_type: s.slate_type });
    router.push(path);
  };

  return (
    <View className="start-card">
      <View className="flex-row items-start justify-between">
        <View className="flex-1 pr-3">
          <Text className="start-title">Start here</Text>
          <Text className="section-subtitle">Three steps to this week&apos;s first lineup</Text>
        </View>
        <Pressable onPress={() => setStartHereHidden(true)} accessibilityRole="button" accessibilityLabel="Hide Start here" hitSlop={10}>
          <Text className="caption">Hide</Text>
        </Pressable>
      </View>

      <Step n={1} title="Pick a slate">
        <Text className="start-step-text">
          A <Term id="slate">slate</Term> is the set of games a contest uses. Most contests run on Sunday Main.
        </Text>
        {slates.length ? (
          <View className="mt-2">
            <SlateList
              slates={slates}
              selectedId={s?.slate_id ?? null}
              onSelect={(id) => {
                choose(id);
                track('start_here_step', { step: 1 });
              }}
            />
          </View>
        ) : !weekData.data ? (
          <View className="mt-2">
            <SkeletonCards count={2} height={76} />
          </View>
        ) : (
          <Text className="start-step-text mt-1">{"DraftKings hasn't posted this week's slates yet."}</Text>
        )}
      </Step>

      <Step n={2} title="See the top plays">
        {s && !s.available ? (
          <Text className="start-step-text">{salariesPendingText(s)}</Text>
        ) : s?.slate_type === 'showdown' ? (
          <>
            <Text className="start-step-text">
              The model&apos;s best <Term id="showdown">Showdown</Term> lineups for this game.
            </Text>
            <Pressable className="btn-outline mt-2" onPress={() => go(2, '/lineups')} accessibilityRole="button">
              <Text className="btn-outline-text">Projected lineups for {name} ›</Text>
            </Pressable>
          </>
        ) : s ? (
          <>
            <Text className="start-step-text">{playsCopy.text}</Text>
            <Pressable className="btn-outline mt-2" onPress={() => go(2, playsRoute)} accessibilityRole="button">
              <Text className="btn-outline-text">{playsCopy.button}</Text>
            </Pressable>
          </>
        ) : null}
      </Step>

      <Step n={3} title="Build a lineup">
        <Text className="start-step-text">
          Tap players to fill each slot under the $50,000 <Term id="salary">salary cap</Term>.
        </Text>
        {s?.available ? (
          <Pressable className="btn mt-2" onPress={() => go(3, '/lineups')} accessibilityRole="button">
            <Text className="btn-text">Build a {name} lineup ›</Text>
          </Pressable>
        ) : null}
      </Step>
    </View>
  );
}
