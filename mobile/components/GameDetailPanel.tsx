import { Text, View } from 'react-native';

import StatusView from '@/components/StatusView';
import { useGameDetail } from '@/lib/game-detail';
import { formatCurrency, formatPercent, formatSigned } from '@/lib/utils';

const ordinal = (n: number) => {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] ?? s[v] ?? s[0]}`;
};
const rank = (r: number | null) => (r ? ` (#${r})` : '');
const vsLeague = (value: number | null, league: number | null) =>
  value != null && league ? `${formatSigned(((value / league) - 1) * 100, 0)}%` : null;

function Section({ title, insight, children }: { title: string; insight?: string; children?: React.ReactNode }) {
  return (
    <View className="detail-section">
      <Text className="detail-title">{title}</Text>
      {children}
      {insight ? <Text className="detail-insight">{insight}</Text> : null}
    </View>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string | null }) {
  return (
    <View className="detail-tile">
      <Text className="detail-tile-label">{label}</Text>
      <Text className="detail-tile-value">{value}</Text>
      {sub ? <Text className="detail-tile-sub">{sub}</Text> : null}
    </View>
  );
}

/** One "label  away | home" comparison row. */
function Row({ label, away, home }: { label: string; away: string; home: string }) {
  return (
    <View className="detail-row">
      <Text className="detail-row-label">{label}</Text>
      <Text className="detail-row-value">{away}</Text>
      <Text className="detail-row-value">{home}</Text>
    </View>
  );
}

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

function Targets({ team, players }: { team: string; players: TopPlayer[] }) {
  if (!players.length) return null;
  return (
    <View className="mt-2">
      <Text className="detail-subhead">{team}</Text>
      {players.slice(0, 4).map((p) => (
        <View key={`${p.name}-${p.position}`} className="detail-target">
          <View className="flex-row items-center justify-between">
            <Text className="detail-target-name" numberOfLines={1}>
              {p.name} <Text className="detail-target-meta">{p.position} · {p.role}</Text>
            </Text>
            <Text className="detail-target-meta">{formatCurrency(p.salary)}</Text>
          </View>
          <Text className="detail-target-meta">
            {p.proj_points != null ? `${p.proj_points.toFixed(1)} proj` : ''}
            {p.ceiling != null ? ` · ${p.ceiling.toFixed(1)} ceil` : ''}
            {p.usage_l3 != null ? ` · ${formatPercent(p.usage_l3, 0)} of touches` : ''}
          </Text>
          {p.reasons.slice(0, 2).map((r, i) => (
            <Text key={i} className="detail-bullet">
              • {r}
            </Text>
          ))}
        </View>
      ))}
    </View>
  );
}

/**
 * The website's Weekly Breakdown for one game, stacked for a phone: postgame
 * recap, Vegas outlook, weather, each offense vs the other defense, tempo,
 * pass/run tendencies, where to attack by position, who gets the ball, and
 * DFS targets.
 */
export default function GameDetailPanel({ gameId }: { gameId: string }) {
  const { detail, error } = useGameDetail(gameId);

  if (!detail) return <StatusView loading={!error} error={error} />;

  const gb = detail.breakdown;
  const g = gb.game;
  const a = gb.away_stats;
  const h = gb.home_stats;
  const L = detail.league;
  const c = g.context;
  const w = g.weather;
  const ins = detail.insights;

  return (
    <View className="detail-panel">
      {gb.postgame?.headline ? (
        <Section title="Postgame">
          <Text className="detail-headline">{gb.postgame.headline}</Text>
          <Bullets items={[...(gb.postgame.result ?? []), ...(gb.postgame.flow ?? [])]} />
        </Section>
      ) : null}

      <Section title="Vegas outlook" insight={ins.vegas}>
        <View className="detail-tiles">
          {c?.home_spread != null ? (
            <Tile label="Spread" value={c.home_spread === 0 ? "Pick'em" : `${c.home_spread < 0 ? g.home : g.away} -${Math.abs(c.home_spread)}`} />
          ) : null}
          {c?.total_line != null ? (
            <Tile label="Total" value={c.total_line.toFixed(1)} sub={gb.total_rank_this_week ? `${ordinal(gb.total_rank_this_week)} highest` : null} />
          ) : null}
          {c?.away_implied_total != null ? (
            <Tile label={`${g.away} implied`} value={c.away_implied_total.toFixed(1)} sub={gb.away_implied_rank_this_week ? `${ordinal(gb.away_implied_rank_this_week)} of the week` : null} />
          ) : null}
          {c?.home_implied_total != null ? (
            <Tile label={`${g.home} implied`} value={c.home_implied_total.toFixed(1)} sub={gb.home_implied_rank_this_week ? `${ordinal(gb.home_implied_rank_this_week)} of the week` : null} />
          ) : null}
        </View>
      </Section>

      {w ? (
        <Section title="Weather" insight={ins.weather}>
          <Text className="detail-text">
            {w.roof === 'dome' ? 'Dome' : w.summary || 'Forecast not available'}
            {w.impact ? ` · Projection impact: ${w.impact}` : ''}
          </Text>
        </Section>
      ) : null}

      <Section title="Team profiles (entering this game)">
        <Row label="" away={g.away} home={g.home} />
        <Row label="Points / game" away={`${a.points_for?.toFixed(1) ?? '-'}${rank(a.points_for_rank)}`} home={`${h.points_for?.toFixed(1) ?? '-'}${rank(h.points_for_rank)}`} />
        <Row label="Points allowed" away={`${a.points_against?.toFixed(1) ?? '-'}${rank(a.points_against_rank)}`} home={`${h.points_against?.toFixed(1) ?? '-'}${rank(h.points_against_rank)}`} />
        <Row label="Yards / play" away={`${a.yards_per_play?.toFixed(2) ?? '-'}${rank(a.yards_per_play_rank)}`} home={`${h.yards_per_play?.toFixed(2) ?? '-'}${rank(h.yards_per_play_rank)}`} />
        <Row label="Yds / play allowed" away={`${a.yards_allowed_per_play?.toFixed(2) ?? '-'}${rank(a.yards_allowed_per_play_rank)}`} home={`${h.yards_allowed_per_play?.toFixed(2) ?? '-'}${rank(h.yards_allowed_per_play_rank)}`} />
        <Row label="Tempo (sec / snap)" away={`${a.tempo_secs?.toFixed(1) ?? '-'}${rank(a.tempo_rank)}`} home={`${h.tempo_secs?.toFixed(1) ?? '-'}${rank(h.tempo_rank)}`} />
        <Row label="Plays / game" away={`${a.plays_per_game?.toFixed(1) ?? '-'}${rank(a.plays_rank)}`} home={`${h.plays_per_game?.toFixed(1) ?? '-'}${rank(h.plays_rank)}`} />
        <Row label="Pass rate" away={formatPercent(a.pass_pct, 0)} home={formatPercent(h.pass_pct, 0)} />
        <Row label="Pass rate faced" away={`${formatPercent(a.opp_pass_pct_allowed, 0)}${rank(a.opp_pass_pct_allowed_rank)}`} home={`${formatPercent(h.opp_pass_pct_allowed, 0)}${rank(h.opp_pass_pct_allowed_rank)}`} />
      </Section>

      {[
        [g.away, g.home, a, h, ins.away_offense],
        [g.home, g.away, h, a, ins.home_offense],
      ].map(([off, def, o, d, insight]) => {
        const offense = o as TeamStatLine;
        const defense = d as TeamStatLine;
        const items = [
          vsLeague(offense.yards_per_play, L.yards_per_play) && `${off} offense: ${vsLeague(offense.yards_per_play, L.yards_per_play)} yards/play vs league`,
          vsLeague(defense.yards_allowed_per_play, L.yards_per_play) && `${def} defense: ${vsLeague(defense.yards_allowed_per_play, L.yards_per_play)} yards/play allowed`,
          vsLeague(offense.points_for, L.points) && `${off} offense: ${vsLeague(offense.points_for, L.points)} points/game`,
          vsLeague(defense.points_against, L.points) && `${def} defense: ${vsLeague(defense.points_against, L.points)} points allowed`,
        ].filter(Boolean) as string[];
        return items.length ? (
          <Section key={off as string} title={`When ${off} has the ball`} insight={insight as string | undefined}>
            <Bullets items={items} />
          </Section>
        ) : null;
      })}

      {ins.tempo || ins.tendency ? (
        <Section title="Tempo and tendencies">
          {ins.tempo ? <Text className="detail-insight">{ins.tempo}</Text> : null}
          {ins.tendency ? <Text className="detail-insight">{ins.tendency}</Text> : null}
        </Section>
      ) : null}

      <Section title="Where to attack (DK pts allowed this season, up to last 8)" insight={ins.positions}>
        {[
          [g.home, g.away, detail.away_def_vs_pos],
          [g.away, g.home, detail.home_def_vs_pos],
        ].map(([off, def, rows]) => (
          <View key={off as string} className="mt-1">
            <Text className="detail-subhead">
              {off as string} offense vs {def as string} defense
            </Text>
            {(rows as PositionMatchup[])
              .filter((r) => r.vs_avg != null)
              .map((r) => (
                <View key={r.position} className="detail-row">
                  <Text className="detail-row-label">{r.position}s</Text>
                  <Text className={`detail-row-value ${(r.vs_avg ?? 0) > 0 ? 'text-positive' : 'text-pending'}`}>
                    {formatSigned((r.vs_avg ?? 0) * 100, 0)}%
                  </Text>
                  <Text className="detail-row-value">{r.allowed ?? '-'} pts{rank(r.rank)}</Text>
                </View>
              ))}
          </View>
        ))}
      </Section>

      <Section title="Who gets the ball (share of targets + carries)" insight={ins.usage}>
        {[
          [g.away, detail.away_usage],
          [g.home, detail.home_usage],
        ].map(([team, rows]) => (
          <View key={team as string} className="mt-1">
            <Text className="detail-subhead">{team as string}</Text>
            {(rows as UsageShare[]).slice(0, 5).map((u) => (
              <View key={u.name} className="detail-row">
                <Text className="detail-row-label" numberOfLines={1}>
                  {u.name} <Text className="detail-target-meta">{u.position}</Text>
                </Text>
                <Text className="detail-row-value">L3 {formatPercent(u.share_l3, 0)}</Text>
                <Text className="detail-row-value">L8 {formatPercent(u.share_l8, 0)}</Text>
              </View>
            ))}
          </View>
        ))}
      </Section>

      <Section title="DFS targets">
        <Targets team={g.away} players={gb.away_top_players} />
        <Targets team={g.home} players={gb.home_top_players} />
      </Section>

      {gb.takeaways.length ? (
        <Section title="Takeaways" insight={ins.trenches}>
          <Bullets items={gb.takeaways} />
        </Section>
      ) : null}
    </View>
  );
}
