import { Text, View } from 'react-native';

import { ChartAxis, DivergingBar, type Side } from '@/components/breakdown/charts';
import { formatCurrency, formatPercent, formatPoints, formatSigned } from '@/lib/utils';

const dash = (v: string | number | null | undefined) => (v == null ? '-' : String(v));

const STATS: { label: string; get: (t: PostgameTeamStats) => string | null }[] = [
  { label: 'Plays', get: (t) => (t.plays != null ? String(t.plays) : null) },
  { label: 'Success rate', get: (t) => (t.success != null ? formatPercent(t.success, 0) : null) },
  { label: 'EPA / play', get: (t) => (t.epa_play != null ? formatSigned(t.epa_play, 2) : null) },
  { label: 'Dropback EPA / play', get: (t) => (t.db_epa != null ? formatSigned(t.db_epa, 2) : null) },
  { label: 'Rush EPA / play', get: (t) => (t.rush_epa != null ? formatSigned(t.rush_epa, 2) : null) },
  { label: 'Yards / play', get: (t) => (t.yards_per_play != null ? t.yards_per_play.toFixed(2) : null) },
  { label: 'Explosive plays', get: (t) => (t.explosive != null ? String(t.explosive) : null) },
  { label: 'Sacks taken', get: (t) => (t.sacks_taken != null ? String(t.sacks_taken) : null) },
  { label: 'Turnovers', get: (t) => (t.turnovers != null ? String(t.turnovers) : null) },
];

function Bullets({ items }: { items: string[] }) {
  return (
    <View className="mt-1 gap-1">
      {items.map((t, i) => (
        <Text key={i} className="detail-bullet">
          • {t}
        </Text>
      ))}
    </View>
  );
}

/**
 * How a finished game actually played out (app.postgame): the result against the line, each team's play-by-play
 * efficiency, which pregame trench matchups were exploited or held, how predictable the result was, and how the
 * pregame DFS targets and the top scorers did. Only the headline and score bullets are always present; the rest
 * appears when the game's play-by-play is in.
 */
export default function PostgameSection({ pg, away, home }: { pg: GamePostgame; away: string; home: string }) {
  const pred = pg.predictability;
  const A = pg.team_stats?.[away];
  const H = pg.team_stats?.[home];
  const matchups = pg.matchups ?? [];
  const dfs = pg.dfs;
  const side = (team: string): Side => (team === away ? 'away' : 'home');
  const rows = A && H ? STATS.filter((s) => s.get(A) != null || s.get(H) != null) : [];

  return (
    <View>
      {pred ? (
        <View className="flex-row flex-wrap gap-2 mb-1">
          <Text className="detail-tile-label">{pred.verdict}</Text>
          {(pred.surprises ?? []).map((t) => (
            <Text key={t} className="detail-tile-label">
              {t}
            </Text>
          ))}
        </View>
      ) : null}
      {pg.headline ? <Text className="detail-headline">{pg.headline}</Text> : null}
      <Bullets items={[...(pg.result ?? []), ...(pg.flow ?? [])]} />
      {pg.note ? <Text className="detail-note">{pg.note}</Text> : null}

      {rows.length && A && H ? (
        <View className="mt-3">
          <Text className="detail-subhead">The game in numbers</Text>
          <View className="detail-row">
            <Text className="detail-row-label" />
            <Text className="detail-row-value">{away}</Text>
            <Text className="detail-row-value">{home}</Text>
          </View>
          {rows.map((s) => (
            <View key={s.label} className="detail-row">
              <Text className="detail-row-label">{s.label}</Text>
              <Text className="detail-row-value">{dash(s.get(A))}</Text>
              <Text className="detail-row-value">{dash(s.get(H))}</Text>
            </View>
          ))}
        </View>
      ) : null}

      {matchups.length ? (
        <View className="mt-3">
          <Text className="detail-subhead">Matchups: pregame expectation vs what happened</Text>
          <Text className="detail-note">
            Expected = the offense&apos;s pregame rate plus the defense&apos;s pregame rate allowed, less the league average (competitive plays only). A bar to the
            right means the offense beat that expectation; gray means within one standard error (played to form).
          </Text>
          {matchups.map((m, i) => (
            <DivergingBar
              key={`${m.label}-${i}`}
              label={m.label}
              side={side(m.offense)}
              value={m.better * m.z}
              max={3}
              muted={m.verdict === 'to form'}
              valueText={`${formatPercent(m.actual, 0)} vs ${formatPercent(m.expected, 0)}`}
            />
          ))}
          <ChartAxis left="Defense won" center="As expected" right="Offense won" />
          <Bullets items={matchups.filter((m) => m.verdict !== 'to form' || m.call).map((m) => m.text)} />
        </View>
      ) : null}

      {pred?.text?.length ? (
        <View className="mt-3">
          <Text className="detail-subhead">How predictable was this?</Text>
          <Bullets items={pred.text} />
        </View>
      ) : null}

      {dfs ? (
        <View className="mt-3">
          <Text className="detail-subhead">DFS results</Text>
          {dfs.text ? <Text className="detail-note">{dfs.text}</Text> : null}
          {dfs.top_scorers.length ? (
            <View className="mt-1">
              <Text className="detail-note">Top scorers</Text>
              {dfs.top_scorers.map((p) => (
                <View key={`${p.name}-${p.team}`} className="detail-row">
                  <Text className="detail-row-label" numberOfLines={1}>
                    {p.name} <Text className="detail-target-meta">{p.team} {p.position}</Text>
                  </Text>
                  <Text className="detail-row-value">{formatPoints(p.points)} pts</Text>
                  <Text className="detail-row-value">
                    {p.salary != null ? formatCurrency(p.salary).replace('.00', '') : '-'}
                    {p.value != null ? ` · ${p.value.toFixed(1)}x` : ''}
                  </Text>
                </View>
              ))}
            </View>
          ) : null}
          {dfs.targets.length ? (
            <View className="mt-2">
              <Text className="detail-note">Pregame targets</Text>
              {dfs.targets.map((p) => (
                <View key={`${p.name}-${p.team}-t`} className="detail-row">
                  <Text className="detail-row-label" numberOfLines={1}>
                    {p.name} <Text className="detail-target-meta">{p.team} {p.position} · {p.role}</Text>
                  </Text>
                  <Text className="detail-row-value">
                    {formatPoints(p.points)} vs {p.proj != null ? formatPoints(p.proj) : '-'} proj
                  </Text>
                  <Text className="detail-row-value">{p.result}</Text>
                </View>
              ))}
            </View>
          ) : null}
          {dfs.note ? <Text className="detail-note">{dfs.note}</Text> : null}
        </View>
      ) : null}
    </View>
  );
}
