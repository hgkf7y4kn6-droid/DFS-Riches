import { Text } from 'react-native';

/**
 * "MIA missing 2 starting CBs" under a RB/WR/TE when the opposing defense is
 * down starting corners (app.game_model). Receivers beat their projections and
 * workhorse pass-catching backs their ceilings in those games; it's already in
 * the numbers shown.
 */
export default function CornersOutNote({ opponent, count, position }: { opponent: string; count?: number | null; position: string }) {
  if (!count || !['RB', 'WR', 'TE'].includes(position)) return null;
  return (
    <Text className="cb-out-note">
      {opponent} missing {count} starting CB{count > 1 ? 's' : ''}
    </Text>
  );
}
