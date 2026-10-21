import { ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import BackLink from '@/components/BackLink';
import BrandHeader from '@/components/BrandHeader';
import SafeAreaView from '@/components/SafeAreaView';
import StatusView from '@/components/StatusView';
import { Term } from '@/components/Term';
import { FLOATING_TAB_BAR } from '@/constants/theme';
import { getTrackRecord, type TrackRecordSlate } from '@/lib/api';
import { createFetchCache, useCachedFetch } from '@/lib/cached-fetch';

const cache = createFetchCache<{ slates: TrackRecordSlate[] }>();

const SLATE_NAME: Record<string, string> = { classic_sunday: 'Sunday Main', classic: 'Full Week' };
const slateName = (id: string) =>
  SLATE_NAME[id] ?? id.replace(/^showdown_/, 'Showdown · ').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

/**
 * "How we did": every finished slate's saved optimal lineups, what they were
 * projected for and what they actually scored, next to the best lineup
 * possible in hindsight. Straight from data/optimal_lineups.json.
 */
export default function Results() {
  const insets = useSafeAreaInsets();
  const { data, loading, error, refresh } = useCachedFetch(cache, 'track', () => getTrackRecord());
  const slates = data?.slates ?? [];
  const main = slates.filter((s) => s.slate_id === 'classic_sunday');
  const proj = main.map((s) => s.lineups.find((l) => l.metric === 'proj_points')).filter(Boolean) as TrackRecordSlate['lineups'];
  const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
  const avgProj = avg(proj.map((l) => l.proj_points));
  const avgActual = avg(proj.map((l) => l.actual));
  const avgBest = avg(main.map((s) => s.best_possible ?? 0).filter(Boolean));

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}>
        <BrandHeader title="How we did" />
        <BackLink />
        <Text className="screen-subtitle">
          Each slate&apos;s <Term id="optimal">projected optimal</Term> lineups, saved before kickoff: what they were projected for, what they
          scored, and the best lineup possible in hindsight.
        </Text>
        <StatusView loading={loading && !data} error={error} onRetry={refresh} />
        {avgProj != null && avgActual != null ? (
          <View className="section card">
            <Text className="section-title">Sunday Main, {main.length} week{main.length === 1 ? '' : 's'}</Text>
            <View className="mt-3 flex-row justify-between">
              <View>
                <Text className="result-big">{avgActual.toFixed(1)}</Text>
                <Text className="caption">avg scored</Text>
              </View>
              <View>
                <Text className="result-big">{avgProj.toFixed(1)}</Text>
                <Text className="caption">avg projected</Text>
              </View>
              {avgBest != null ? (
                <View>
                  <Text className="result-big">{avgBest.toFixed(1)}</Text>
                  <Text className="caption">avg best possible</Text>
                </View>
              ) : null}
            </View>
            <Text className="caption mt-3">The projection-optimal lineup, in DraftKings points.</Text>
          </View>
        ) : null}
        {slates.map((s) => (
          <View key={`${s.season}-${s.week}-${s.slate_id}`} className="result-card">
            <Text className="result-title">
              Week {s.week} · {slateName(s.slate_id)}
            </Text>
            {s.lineups.map((l) => (
              <View key={l.label} className="result-row">
                <Text className="dfs-name flex-1">{l.label.replace('Optimal - ', 'Optimal · ')}</Text>
                <Text className="dfs-meta">proj {l.proj_points.toFixed(1)}</Text>
                <Text className={`result-score ${l.actual >= l.proj_points ? 'text-positive' : 'text-negative'}`}>{l.actual.toFixed(1)}</Text>
              </View>
            ))}
            {s.best_possible != null ? <Text className="dfs-meta mt-1">Best possible: {s.best_possible.toFixed(1)}</Text> : null}
          </View>
        ))}
        {data && !slates.length ? <Text className="home-empty-state">No finished slates yet.</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}
