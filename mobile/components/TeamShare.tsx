import { Text } from 'react-native';

/**
 * The small usage indicator after a player's snap share: his share of the
 * team's RB/WR/TE touches and DK points (last 3 games) with the team rank of
 * each, e.g. " · 38% tch #1 · 31% FP #2". Renders inside a meta <Text>.
 */
export default function TeamShareText({ share }: { share?: TeamShare | null }) {
  if (!share) return null;
  return (
    <Text
      className="team-share"
      accessibilityLabel={`${share.touch_pct}% of team skill touches, rank ${share.touch_rank} of ${share.of}; ${share.fp_pct}% of skill fantasy points, rank ${share.fp_rank}`}>
      {' · '}
      {Math.round(share.touch_pct)}% tch <Text className="team-share-rank">#{share.touch_rank}</Text> · {Math.round(share.fp_pct)}% FP{' '}
      <Text className="team-share-rank">#{share.fp_rank}</Text>
    </Text>
  );
}
