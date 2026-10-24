import { Text, View } from 'react-native';

import { formatPoints } from '@/lib/utils';

/**
 * A scored Pro Picks position, spot by spot: who the user ranked at each spot (his actual DraftKings points
 * and where he finished) beside who actually finished at that spot (and his DraftKings points). Tied players
 * share a spot number, so a tie at the cut-off can add a row past the list size. A ranked player who didn't play
 * scores 0 and the picks below him count a spot higher, so "exact" comes from the server (row.exact).
 */
export default function PicksComparison({
  state,
  position,
  picks,
  byId,
}: {
  state: ProPicksState;
  position: PickPosition;
  picks: number[];
  byId: Map<number, PickPlayer>;
}) {
  const size = state.sizes[position];
  const scored = state.my_result?.positions[position];
  const actual = state.actual_top?.[position] ?? [];
  const mine = new Set(picks);
  const rows = Math.max(size, actual.length);
  const name = (id: number) => byId.get(id)?.name ?? `#${id}`;
  const team = (id: number) => byId.get(id)?.team ?? '';

  return (
    <View className="lineup-card">
      <View className="lineup-row">
        <Text className="lineup-slot">#</Text>
        <Text className="input-label flex-1">Your pick</Text>
        <Text className="input-label flex-1">Actually finished</Text>
      </View>
      {Array.from({ length: rows }, (_, i) => {
        const pid = i < size ? picks[i] : undefined;
        const row = scored?.rows.find((r) => r.ranked === i + 1);
        const a = actual[i];
        const outcome = !row
          ? null
          : row.ruled_out
            ? { text: "Ruled out · 0 pts · doesn't count against you", tone: 'text-muted-foreground' }
            : row.points <= 0
              ? { text: row.finished ? `Missed · finished #${row.finished}` : 'Missed', tone: 'text-negative' }
              : row.exact
                ? { text: `Exact spot · +${formatPoints(row.points)}`, tone: 'text-positive' }
                : { text: `Finished #${row.finished} · +${formatPoints(row.points)}`, tone: 'text-positive' };
        return (
          <View key={i} className="lineup-row items-start">
            <Text className="lineup-slot">{i < size ? `${i + 1}.` : ''}</Text>
            <View className="flex-1 pr-2">
              {pid != null ? (
                <>
                  <Text className="lineup-player-name" numberOfLines={1}>
                    {name(pid)}
                  </Text>
                  <Text className="lineup-player-meta" numberOfLines={1}>
                    {team(pid)} · {formatPoints(row?.dk ?? null)} DK pts
                  </Text>
                  {outcome ? (
                    <Text className={`lineup-player-meta ${outcome.tone}`} numberOfLines={1}>
                      {outcome.text}
                    </Text>
                  ) : null}
                </>
              ) : (
                <Text className="caption">{i < size ? 'Not ranked' : ''}</Text>
              )}
            </View>
            <View className="flex-1">
              {a ? (
                <>
                  <Text className="lineup-player-name" numberOfLines={1}>
                    {a.spot !== i + 1 ? `#${a.spot} (tie) ` : ''}
                    {name(a.id)}
                  </Text>
                  <Text className="lineup-player-meta" numberOfLines={1}>
                    {team(a.id)} · {formatPoints(a.points)} DK pts
                  </Text>
                  {mine.has(a.id) ? <Text className="lineup-player-meta text-positive">✓ On your list</Text> : null}
                </>
              ) : null}
            </View>
          </View>
        );
      })}
    </View>
  );
}
