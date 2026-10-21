import { router } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { SkeletonRows } from '@/components/Skeleton';
import { usePlays } from '@/lib/plays';
import { usePrefs } from '@/lib/prefs-context';
import { formatCurrency } from '@/lib/utils';

const POSITIONS = ['QB', 'RB', 'WR', 'TE'] as const;

/**
 * Home's lead card for what the user plays (prefs.focus): the model's top
 * cash or tournament play at each position on the current slate, with a link
 * to the full tab. Nothing for "both" (Start here covers it).
 */
export default function HomeTopPlays() {
  const { prefs } = usePrefs();
  const contest = prefs.focus === 'cash' || prefs.focus === 'gpp' ? prefs.focus : null;
  const { data, loading } = usePlays(contest ?? 'cash', contest != null);
  if (!contest) return null;
  const ready = data?.available ? data : null;
  const own = (p: PlayPlayer) => (contest === 'cash' ? p.ownership.cash : p.ownership.large_gpp);

  return (
    <View className="section card">
      <Text className="section-title">{contest === 'cash' ? 'Your top safe plays' : 'Your top tournament plays'}</Text>
      <Text className="section-subtitle">
        {ready ? `${ready.slate.label} · the model's #1 at each position` : 'The model’s #1 at each position'}
      </Text>
      {loading && !ready ? <SkeletonRows rows={4} /> : null}
      {data && !data.available ? <Text className="home-empty-state">{data.reason}</Text> : null}
      {ready ? (
        <View className="mt-2">
          {POSITIONS.map((pos) => {
            const p = ready.rankings[pos]?.[0];
            if (!p) return null;
            return (
              <View key={pos} className="top-play-row">
                <Text className="top-play-pos">{pos}</Text>
                <View className="flex-1">
                  <Text className="dfs-name" numberOfLines={1}>
                    {p.name}
                  </Text>
                  <Text className="dfs-meta">
                    {p.team} vs {p.opponent} · {p.final.toFixed(1)} proj{own(p) != null ? ` · ${Math.round(own(p) ?? 0)}% owned` : ''}
                  </Text>
                </View>
                <Text className="dfs-salary">{formatCurrency(p.salary)}</Text>
              </View>
            );
          })}
        </View>
      ) : null}
      <Pressable className="btn-outline mt-3" onPress={() => router.push(contest === 'cash' ? '/cash' : '/gpp')} accessibilityRole="button">
        <Text className="btn-outline-text">{contest === 'cash' ? 'All safe plays ›' : 'All tournament plays ›'}</Text>
      </Pressable>
    </View>
  );
}
