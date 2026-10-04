import { useState } from 'react';
import { Modal, Pressable, ScrollView, Text, View } from 'react-native';

import { useWeek } from '@/lib/week-context';

const WEEKS = Array.from({ length: 18 }, (_, i) => i + 1);

/**
 * The header's season / week button ("2026 · Week 4"). Tap to view another
 * season or week -- every tab follows -- or jump back to the current week.
 */
export default function WeekPicker() {
  const { season, week, current, setSeasonWeek } = useWeek();
  const [open, setOpen] = useState(false);
  const [pickSeason, setPickSeason] = useState<number | null>(null);
  if (!season || !week) return null;
  const viewingCurrent = !current || (current.season === season && current.week === week);
  const seasons = current ? [current.season, current.season - 1, current.season - 2] : [season];
  const shownSeason = pickSeason ?? season;
  const choose = (s: number, w: number) => {
    setSeasonWeek({ season: s, week: w });
    setOpen(false);
    setPickSeason(null);
  };
  return (
    <>
      <Pressable
        className={`week-pill ${viewingCurrent ? '' : 'week-pill-past'}`}
        onPress={() => setOpen(true)}
        accessibilityRole="button"
        accessibilityLabel={`Season ${season}, week ${week}. Change season or week`}>
        <Text className="week-pill-season">{season}</Text>
        <Text className="week-pill-week">Week {week} ▾</Text>
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable className="week-backdrop" onPress={() => setOpen(false)} accessibilityLabel="Close">
          <Pressable className="week-sheet" onPress={() => {}}>
            <Text className="week-sheet-title">Season and week</Text>
            <Text className="input-label">Season</Text>
            <View className="flex-row flex-wrap gap-2">
              {seasons.map((s) => {
                const active = s === shownSeason;
                return (
                  <Pressable
                    key={s}
                    className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
                    onPress={() => setPickSeason(s)}
                    accessibilityRole="button"
                    aria-pressed={active}>
                    <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{s}</Text>
                  </Pressable>
                );
              })}
            </View>
            <Text className="input-label mt-3">Week</Text>
            <ScrollView contentContainerClassName="flex-row flex-wrap gap-2" style={{ maxHeight: 220 }}>
              {WEEKS.map((w) => {
                const active = shownSeason === season && w === week;
                const isNow = current && shownSeason === current.season && w === current.week;
                const future = current && shownSeason === current.season && w > current.week;
                return (
                  <Pressable
                    key={w}
                    className={`filter-chip ${active ? 'filter-chip-active' : ''} ${future ? 'opacity-50' : ''}`}
                    onPress={() => choose(shownSeason, w)}
                    accessibilityRole="button"
                    aria-pressed={active}
                    accessibilityLabel={`Week ${w}${isNow ? ', current week' : ''}`}>
                    <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>
                      {w}
                      {isNow ? ' •' : ''}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
            {!viewingCurrent && current ? (
              <Pressable className="btn-outline mt-3" onPress={() => (setSeasonWeek(null), setOpen(false))} accessibilityRole="button">
                <Text className="btn-outline-text">
                  Back to the current week ({current.season} · Week {current.week})
                </Text>
              </Pressable>
            ) : null}
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}
