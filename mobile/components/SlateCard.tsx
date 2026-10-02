import { Image, Pressable, Text, View } from 'react-native';

import LineupBuilder from '@/components/LineupBuilder';
import ListHeading from '@/components/ListHeading';
import OptimalLineups from '@/components/OptimalLineups';
import icons from '@/constants/icons';
import { useThemeColors } from '@/constants/theme';
import { slateStatus } from '@/lib/games';
import { formatDayPart, formatGameDate, formatGameTime, formatStatusLabel } from '@/lib/utils';

interface Props {
  slate: Slate;
  expanded: boolean;
  onToggle: () => void;
  now: number;
}

function slateTitle(slate: Slate): string {
  if (slate.slate_type === 'showdown' && slate.games[0]) return `${slate.games[0].away} @ ${slate.games[0].home}`;
  if (slate.slate_id === 'classic_sunday') return 'Sunday Main';
  if (slate.slate_id === 'classic') return 'Full Week';
  return slate.label;
}

/**
 * One DraftKings slate as a tappable card. Collapsed: type, title, games and
 * first lock. Tap to expand into its projected optimal lineups and the
 * lineup builder (build and save lineups for this slate); tap again to
 * collapse.
 */
export default function SlateCard({ slate, expanded, onToggle, now }: Props) {
  const colors = useThemeColors();
  const { status, daysLeft, firstKickoff } = slateStatus(slate, now);
  const kind = slate.slate_type === 'showdown' ? `Showdown${slate.day_part ? ` · ${formatDayPart(slate.day_part)}` : ''}` : 'Classic';
  const games = `${slate.games.length} game${slate.games.length === 1 ? '' : 's'}`;
  const lock = firstKickoff ? `${status === 'upcoming' ? 'Locks' : 'Locked'} ${formatGameDate(firstKickoff)} · ${formatGameTime(firstKickoff)}` : null;

  return (
    <View className={`slate-card ${expanded ? 'slate-card-active' : ''}`}>
      <Pressable
        className="slate-card-header"
        onPress={onToggle}
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        accessibilityLabel={`${slate.label}, ${expanded ? 'collapse' : 'show lineups'}`}>
        <View className="flex-1 pr-3">
          <Text className="slate-card-status">
            {kind} · {slate.available ? formatStatusLabel(status, daysLeft) : 'No salaries yet'}
          </Text>
          <Text className="slate-card-title">{slateTitle(slate)}</Text>
          <Text className="slate-card-meta">{[lock, games].filter(Boolean).join(' · ')}</Text>
        </View>
        <Image
          source={icons.chevron}
          style={{ width: 16, height: 16, tintColor: colors.foreground, transform: [{ rotate: expanded ? '180deg' : '0deg' }] }}
        />
      </Pressable>
      {expanded ? (
        <View className="slate-card-body">
          <Text className="list-title mb-3">Projected optimal</Text>
          <OptimalLineups />
          <ListHeading title="Build & save lineups" />
          <LineupBuilder />
        </View>
      ) : null}
    </View>
  );
}
