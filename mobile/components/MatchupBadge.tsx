import { Text, View } from 'react-native';

import { matchupTone, useMatchups, type MatchupTone } from '@/lib/matchups-context';

// Full class names so Tailwind keeps them.
const TONE: Record<MatchupTone, { pill: string; text: string }> = {
  soft: { pill: 'matchup-badge matchup-soft', text: 'matchup-text matchup-soft-text' },
  neutral: { pill: 'matchup-badge matchup-neutral', text: 'matchup-text matchup-neutral-text' },
  tough: { pill: 'matchup-badge matchup-tough', text: 'matchup-text matchup-tough-text' },
};

/**
 * Where the player's opponent ranks against his position: by DK points
 * allowed and by the position's efficiency metric, raw or strength-of-schedule
 * adjusted (the user's choice). #32 = allows the most, so green is a soft
 * matchup and red a tough one.
 */
export default function MatchupBadge({ opponent, position }: { opponent?: string | null; position?: string | null }) {
  const { lookup } = useMatchups();
  const m = lookup(opponent, position);
  if (!m) return null;
  const tone = TONE[matchupTone((m.fp_rank + m.eff_rank) / 2, m.teams)];
  const label = m.position === 'DST' ? `${m.team} offense` : `${m.team} vs ${m.position}`;
  return (
    <View className={tone.pill} accessibilityLabel={`${label}: number ${m.fp_rank} in fantasy points allowed, number ${m.eff_rank} in ${m.effLabel}`}>
      <Text className={tone.text}>
        {label}
        {m.mode === 'adj' ? ' (SOS)' : ''} · #{m.fp_rank} FP · #{m.eff_rank} {m.effLabel}
      </Text>
    </View>
  );
}
