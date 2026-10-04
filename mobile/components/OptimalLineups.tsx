import { Pressable, Text, View } from 'react-native';

import { LineupRow, Totals } from '@/components/LineupRows';
import StatusView from '@/components/StatusView';
import { OPTIMAL_STATUS_TEXT } from '@/constants/data';
import { fromOptimal } from '@/lib/lineups';
import { formatCurrency, formatEt, formatPoints } from '@/lib/utils';
import { type LineupScope, useLineups, useWeek } from '@/lib/week-context';

function statusLine(opt: OptimalResponse): string {
  if (opt.status === 'live') return `${OPTIMAL_STATUS_TEXT.live} (last change ${formatEt(opt.saved_at)})`;
  if (opt.status === 'saved') return `${OPTIMAL_STATUS_TEXT.saved} (saved ${formatEt(opt.saved_at)})`;
  if (opt.status === 'final') return `${OPTIMAL_STATUS_TEXT.final} (${formatEt(opt.results_at)})`;
  return OPTIMAL_STATUS_TEXT.none;
}

function OptimalCard({ lineup, onEdit }: { lineup: OptimalLineup; onEdit?: () => void }) {
  const hindsight = lineup.metric === 'actual';
  return (
    <View className="lineup-card">
      <View className="lineup-card-header">
        <Text className="lineup-title">{lineup.label}</Text>
        {onEdit ? (
          <Pressable onPress={onEdit} accessibilityRole="button" accessibilityLabel={`Edit ${lineup.label} in the builder`}>
            <Text className="link-text">Edit in builder</Text>
          </Pressable>
        ) : null}
      </View>
      {lineup.players.map((p, i) => (
        <LineupRow key={`${p.slot}-${i}`} slot={p.slot} player={p} />
      ))}
      <Totals
        items={[
          { label: 'Salary', value: formatCurrency(lineup.salary) },
          ...(hindsight ? [] : [{ label: 'Proj', value: formatPoints(lineup.proj_points) }, { label: 'Ceiling', value: formatPoints(lineup.ceiling) }]),
          ...(lineup.actual != null ? [{ label: 'Actual', value: formatPoints(lineup.actual) }] : []),
        ]}
      />
    </View>
  );
}

/** The projected optimal lineups for the selected slate (and, once final, the best possible);
 *  "Edit in builder" copies one into the `scope` builder's active lineup. */
export default function OptimalLineups({ scope = '' }: { scope?: LineupScope }) {
  const { selectedSlate, optimal, players } = useWeek();
  const { activeLineup, setLineup } = useLineups(scope);
  if (!selectedSlate) return null;
  const opt = optimal.data;
  const pool = players.data?.players ?? [];
  const editable = selectedSlate.available && pool.length > 0 && opt?.status === 'live';

  return (
    <View>
      <StatusView
        loading={optimal.loading}
        error={optimal.error}
        empty={opt && opt.lineups.length === 0 ? (selectedSlate.available ? 'No optimal lineups yet' : 'DraftKings has not posted salaries for this slate yet') : null}
      />
      {opt && opt.lineups.length > 0 ? (
        <>
          <Text className="lineup-status">{statusLine(opt)}</Text>
          {opt.lineups.map((lu) => (
            <OptimalCard
              key={lu.label}
              lineup={lu}
              onEdit={editable ? () => setLineup(activeLineup, fromOptimal(lu, selectedSlate.slate_type, pool)) : undefined}
            />
          ))}
          {opt.hindsight ? <OptimalCard lineup={opt.hindsight} /> : null}
        </>
      ) : null}
    </View>
  );
}
