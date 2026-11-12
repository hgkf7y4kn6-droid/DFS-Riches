import { Linking, Pressable, Text, View } from 'react-native';

import ExpandableCard from '@/components/ExpandableCard';
import StatusView from '@/components/StatusView';
import { HOME_SECTIONS } from '@/constants/data';
import { getFreeContests } from '@/lib/api';
import { createFetchCache, useCachedFetch } from '@/lib/cached-fetch';
import { formatEt } from '@/lib/utils';

const cache = createFetchCache<FreeContestsResponse>();

/** DraftKings' "unlimited" fields come through as a huge field size. */
const field = (c: FreeContest) =>
  c.field_size >= 1_000_000
    ? `${c.entries.toLocaleString('en-US')} entered · unlimited`
    : `${c.entries.toLocaleString('en-US')}/${c.field_size.toLocaleString('en-US')} entered`;

/** Free NFL contests on DraftKings that pay cash; opens itself when there are any. */
export default function FreeContests() {
  const { data, error, loading } = useCachedFetch(cache, 'free', getFreeContests);
  const rows = data?.contests ?? [];
  const section = HOME_SECTIONS.free;
  return (
    <ExpandableCard
      // Remounts once the list arrives, so it opens when there's something to enter.
      key={data ? (rows.length ? 'some' : 'none') : 'loading'}
      title={section.title}
      subtitle={section.subtitle}
      aside={data ? (rows.length ? `${rows.length} open` : 'None now') : undefined}
      defaultExpanded={rows.length > 0}>
      {!data ? (
        <StatusView loading={loading} error={error} />
      ) : rows.length ? (
        rows.map((c) => (
          <Pressable
            key={c.id}
            className="pl-row"
            onPress={() => Linking.openURL(`https://www.draftkings.com/draft/contest/${c.id}`)}
            accessibilityRole="link"
            accessibilityLabel={`${c.name}, free, ${c.cash ?? ''} in prizes. Open on DraftKings`}>
            <View className="pl-row-header">
              <Text className="pl-type flex-1 pr-2" numberOfLines={2}>
                {c.name}
              </Text>
              <Text className="pl-net text-positive">{c.cash ?? `$${c.prize_pool.toLocaleString('en-US')}`}</Text>
            </View>
            <Text className="caption mt-1">
              {[c.game_type, c.slate, formatEt(c.start_utc), field(c)].filter(Boolean).join(' · ')}
            </Text>
          </Pressable>
        ))
      ) : (
        <Text className="home-empty-state">No free NFL contests paying cash right now. Check back later.</Text>
      )}
    </ExpandableCard>
  );
}
