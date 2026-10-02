import { Image, Pressable, Text, View } from 'react-native';

import DfsPlayerRow from '@/components/dfs/DfsPlayerRow';
import icons from '@/constants/icons';
import { useThemeColors } from '@/constants/theme';
import { formatCurrency, formatPercent } from '@/lib/utils';

/**
 * One model lineup (cash or GPP) as a vertical card. Collapsed: label,
 * construction and totals. Tap to expand into the players, the idea, why
 * it wins, strengths and risks, and any checklist misses; tap again to
 * collapse.
 */
export default function DfsLineupCard({ lineup, expanded, onToggle }: { lineup: DfsLineup; expanded: boolean; onToggle: () => void }) {
  const colors = useThemeColors();
  const misses = lineup.eval.checklist.filter((c) => !c.ok).map((c) => c.item);
  return (
    <View className={`slate-card ${expanded ? 'slate-card-active' : ''}`}>
      <Pressable className="slate-card-header" onPress={onToggle} accessibilityRole="button" accessibilityState={{ expanded }}>
        <View className="flex-1 pr-3">
          <Text className="slate-card-status">
            {lineup.construction} · quality {Math.round(lineup.eval.quality)}
          </Text>
          <Text className="slate-card-title">{lineup.label}</Text>
          <Text className="slate-card-meta">
            {lineup.final.toFixed(1)} proj · {lineup.floor.toFixed(1)} floor · {lineup.ceiling.toFixed(1)} ceil ·{' '}
            {formatPercent(lineup.eval.ownership_total / 100, 0)} own · {formatCurrency(lineup.salary)}
          </Text>
        </View>
        <Image
          source={icons.chevron}
          style={{ width: 16, height: 16, tintColor: colors.foreground, transform: [{ rotate: expanded ? '180deg' : '0deg' }] }}
        />
      </Pressable>
      {expanded ? (
        <View className="slate-card-body">
          <Text className="detail-insight mt-0">{lineup.idea}</Text>
          {lineup.players.map((p, i) => (
            <DfsPlayerRow key={`${p.id}-${i}`} player={p} />
          ))}
          {lineup.eval.win_scenario ? (
            <>
              <Text className="detail-title mt-3">How it wins</Text>
              <Text className="detail-bullet">{lineup.eval.win_scenario}</Text>
            </>
          ) : null}
          {lineup.strengths?.length ? (
            <>
              <Text className="detail-title mt-3">Strengths</Text>
              {lineup.strengths.map((s, i) => (
                <Text key={i} className="detail-bullet">
                  • {s}
                </Text>
              ))}
            </>
          ) : null}
          {lineup.risks?.length || misses.length ? (
            <>
              <Text className="detail-title mt-3">Risks</Text>
              {[...(lineup.risks ?? []), ...misses.map((m) => `Checklist miss: ${m}`)].map((s, i) => (
                <Text key={i} className="detail-bullet">
                  • {s}
                </Text>
              ))}
            </>
          ) : null}
          {lineup.eval.audit?.biggest_failure_point ? (
            <Text className="detail-insight">Biggest failure point: {lineup.eval.audit.biggest_failure_point}</Text>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}
