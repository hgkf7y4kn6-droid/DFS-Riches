import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { useWeek } from '@/lib/week-context';

const SHOWN_NAMES = 8;

/**
 * What's missing or out of date behind the selected slate's numbers: inputs the server couldn't load or
 * refresh (server `warnings`), and DraftKings players it couldn't match to Sleeper, which have no projection.
 * A quiet one-line note by the player pool that opens for the details; nothing when everything is in order.
 */
export default function DataNotice() {
  const { players } = useWeek();
  const [open, setOpen] = useState(false);
  const data = players.data;
  if (!data) return null;
  const warnings = data.warnings ?? [];
  const unmatched = data.unmatched_dk_names ?? [];
  const count = warnings.length + (unmatched.length ? 1 : 0);
  if (!count) return null;
  const summary = [
    unmatched.length ? `${unmatched.length} player${unmatched.length === 1 ? '' : 's'} without a projection` : null,
    warnings.length ? `${warnings.length} data note${warnings.length === 1 ? '' : 's'}` : null,
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <View className="mb-2">
      <Pressable
        onPress={() => setOpen((o) => !o)}
        accessibilityRole="button"
        aria-expanded={open}
        accessibilityLabel={`${summary}. ${open ? 'Hide' : 'Show'} details`}
        className="min-h-9 flex-row items-center">
        <Text className="caption flex-1">{`ⓘ ${summary}`}</Text>
        <Text className="picker-seg-caret">{open ? '▴' : '▾'}</Text>
      </Pressable>
      {open ? (
        <View className="mt-1 rounded-xl border border-border bg-card px-3 py-2" accessibilityRole="alert">
          {warnings.map((w) => (
            <Text key={w} className="edit-banner-text">
              {w}
            </Text>
          ))}
          {unmatched.length ? (
            <Text className="edit-banner-text">
              {`${unmatched.length} of ${data.total_count} DraftKings players couldn't be matched to Sleeper: ${unmatched
                .slice(0, SHOWN_NAMES)
                .join(', ')}${unmatched.length > SHOWN_NAMES ? `, +${unmatched.length - SHOWN_NAMES} more` : ''}.`}
            </Text>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}
