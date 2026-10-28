import { Text, View } from 'react-native';

import { useWeek } from '@/lib/week-context';

const SHOWN_NAMES = 8;

/**
 * What's missing or out of date behind the selected slate's numbers: inputs the server couldn't load or
 * refresh (server `warnings`), and DraftKings players it couldn't match to Sleeper, which have no projection.
 * Renders nothing when everything is in order.
 */
export default function DataNotice() {
  const { players } = useWeek();
  const data = players.data;
  if (!data) return null;
  const warnings = data.warnings ?? [];
  const unmatched = data.unmatched_dk_names ?? [];
  if (!warnings.length && !unmatched.length) return null;
  return (
    <View className="edit-banner" accessibilityRole="alert">
      <Text className="edit-banner-title">Check these numbers</Text>
      {warnings.map((w) => (
        <Text key={w} className="edit-banner-text">
          {w}
        </Text>
      ))}
      {unmatched.length ? (
        <Text className="edit-banner-text">
          {`${unmatched.length} of ${data.total_count} DraftKings players couldn't be matched to Sleeper, so they have no projection: ${unmatched
            .slice(0, SHOWN_NAMES)
            .join(', ')}${unmatched.length > SHOWN_NAMES ? `, +${unmatched.length - SHOWN_NAMES} more` : ''}.`}
        </Text>
      ) : null}
    </View>
  );
}
