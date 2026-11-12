import { Text } from 'react-native';

/**
 * "Plays 78% · Wed DNP · Thu LP · Fri FP" under a Questionable player: his chance of playing from this week's
 * practice report (app.injury_news), already in the projection shown.
 */
export default function PlayChanceNote({ injury, chance, practice }: { injury?: string | null; chance?: number | null; practice?: string | null }) {
  if (injury !== 'Q' || chance == null) return null;
  const tone = chance >= 0.85 ? 'play-chance-high' : chance < 0.6 ? 'play-chance-low' : '';
  return (
    <Text className={`play-chance-note ${tone}`}>
      {chance >= 1 ? 'Active: not on the inactives' : `Plays ${Math.round(chance * 100)}%`}
      {practice ? ` · ${practice}` : ''}
    </Text>
  );
}
