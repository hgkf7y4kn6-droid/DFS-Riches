import { Text, View } from 'react-native';

import { RankBar, type Side } from '@/components/breakdown/charts';
import TrendChips from '@/components/TrendChips';
import { TREND_LEGEND } from '@/lib/trend';

// Each offense metric and the defense metric it runs into.
const PAIRS: { off: string; def: string; label: string }[] = [
  { off: 'yards', def: 'yards', label: 'Yards / game' },
  { off: 'pass_yards', def: 'pass_yards', label: 'Passing yards / game' },
  { off: 'rush_yards', def: 'rush_yards', label: 'Rushing yards / game' },
  { off: 'fantasy_points', def: 'fantasy_points', label: 'DK points / game (QB, RB, WR, TE)' },
  { off: 'giveaways', def: 'takeaways', label: 'Giveaways vs takeaways / game' },
];

const fmt = (v: number, unit: string) => (unit ? v.toFixed(1) : v.toFixed(2));

function UnitRow({ team, side, kind, metric, league, of }: {
  team: string;
  side: Side;
  kind: 'off' | 'def';
  metric: UnitMetric | undefined;
  league: UnitLeague | undefined;
  of: number;
}) {
  if (!metric || !league) return null;
  return (
    <View className="mb-1">
      <RankBar label={`${team} ${kind === 'off' ? 'offense' : 'defense'}`} side={side} rank={metric.rank} of={of} value={fmt(metric.value, league.unit)} />
      <TrendChips windows={metric} baseline={metric.value} better={league.better} format={(v) => fmt(v, league.unit)} />
    </View>
  );
}

/**
 * Each offense against the defense it faces, unit by unit: per-game yards
 * (total, passing, rushing), DK points and turnovers this season, each with
 * its league rank as a meter (#1 = best: most for an offense, fewest allowed
 * for a defense, fewest giveaways, most takeaways) and its L3 / L6 / L9 trend
 * against the season average.
 */
export default function UnitMatchups({ units, away, home }: { units: GameUnits; away: string; home: string }) {
  const of = units.teams_ranked;
  const sides: [string, Side, TeamUnits, string, Side, TeamUnits][] = [
    [away, 'away', units.away, home, 'home', units.home],
    [home, 'home', units.home, away, 'away', units.away],
  ];
  return (
    <View>
      <Text className="detail-note">
        Season to date ({units.away.games} and {units.home.games} games). Bar = league rank (fuller = better, #1 = best of {of}). Trend chips
        compare the last 3 / 6 / 9 games with the season average and appear once that many games are played. {TREND_LEGEND}.
      </Text>
      {sides.map(([off, offSide, offUnits, def, defSide, defUnits]) => (
        <View key={off} className="mt-3">
          <Text className="detail-subhead">
            {off} offense vs {def} defense
          </Text>
          {PAIRS.map((p) => (
            <View key={p.off} className="mt-1.5">
              <Text className="chart-heading">
                {p.label}
                {units.league.offense[p.off]?.avg != null ? (
                  <Text className="chart-heading-sub"> · league {fmt(units.league.offense[p.off].avg!, units.league.offense[p.off].unit)}</Text>
                ) : null}
              </Text>
              <UnitRow team={off} side={offSide} kind="off" metric={offUnits.offense[p.off]} league={units.league.offense[p.off]} of={of} />
              <UnitRow team={def} side={defSide} kind="def" metric={defUnits.defense[p.def]} league={units.league.defense[p.def]} of={of} />
            </View>
          ))}
        </View>
      ))}
    </View>
  );
}
