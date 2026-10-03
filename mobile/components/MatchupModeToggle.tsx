import { Pressable, Text, View } from 'react-native';

import { useMatchups } from '@/lib/matchups-context';

const OPTIONS: { mode: MatchupMode; label: string }[] = [
  { mode: 'raw', label: 'Raw' },
  { mode: 'adj', label: 'Schedule-adjusted' },
];

/** Switch every matchup badge between raw and strength-of-schedule adjusted ranks. */
export default function MatchupModeToggle({ compact = false }: { compact?: boolean }) {
  const { mode, setMode, data } = useMatchups();
  return (
    <View className="mb-2">
      <View className="flex-row flex-wrap items-center gap-2">
        <Text className="matchup-toggle-label">Matchup ranks</Text>
        {OPTIONS.map((o) => {
          const active = o.mode === mode;
          return (
            <Pressable
              key={o.mode}
              className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
              onPress={() => setMode(o.mode)}
              accessibilityRole="radio"
              accessibilityState={{ selected: active }}>
              <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
      {!compact ? (
        <Text className="dfs-reason">
          #32 = the defense allowing the most to that position this season (its last {data?.window ?? 8} games once it has played that many), #1 the least (green soft, red tough).{' '}
          {mode === 'adj'
            ? 'Schedule-adjusted judges each game against what that offense usually produces, so soft or brutal schedules don\'t skew the ranks.'
            : 'Raw is points and efficiency allowed as-is; switch to schedule-adjusted to strip out who they happened to face.'}
        </Text>
      ) : null}
    </View>
  );
}
