import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { useMatchups } from '@/lib/matchups-context';

const OPTIONS: { mode: MatchupMode; label: string; hint: string }[] = [
  { mode: 'raw', label: 'Raw', hint: 'Points and efficiency allowed as-is' },
  { mode: 'adj', label: 'Schedule-adjusted', hint: 'Strips out the offenses each defense happened to face' },
];

/** One dropdown that switches every matchup badge between raw and strength-of-schedule adjusted ranks. */
export default function MatchupModeToggle({ compact = false }: { compact?: boolean }) {
  const { mode, setMode, data } = useMatchups();
  const [open, setOpen] = useState(false);
  const current = OPTIONS.find((o) => o.mode === mode) ?? OPTIONS[0];
  return (
    <View className="mb-2">
      <View className="flex-row items-center gap-2">
        <Text className="matchup-toggle-label">Matchup ranks</Text>
        <Pressable
          className="filter-chip flex-row items-center"
          onPress={() => setOpen((o) => !o)}
          accessibilityRole="button"
          aria-expanded={open}
          accessibilityLabel={`Matchup ranks: ${current.label}. Change`}>
          <Text className="filter-chip-text">
            {current.label} {open ? '▴' : '▾'}
          </Text>
        </Pressable>
      </View>
      {open ? (
        <View className="matchup-menu" accessibilityRole="radiogroup">
          {OPTIONS.map((o) => {
            const active = o.mode === mode;
            return (
              <Pressable
                key={o.mode}
                className={`matchup-menu-item ${active ? 'matchup-menu-item-active' : ''}`}
                onPress={() => {
                  setMode(o.mode);
                  setOpen(false);
                }}
                accessibilityRole="radio"
                aria-checked={active}>
                <Text className="matchup-menu-label">
                  {active ? '✓ ' : ''}
                  {o.label}
                </Text>
                <Text className="matchup-menu-hint">{o.hint}</Text>
              </Pressable>
            );
          })}
        </View>
      ) : null}
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
