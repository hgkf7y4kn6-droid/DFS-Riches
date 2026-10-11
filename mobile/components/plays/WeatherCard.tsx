import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { useExpandedWidth } from '@/components/dfs/useCardWidth';
import { weatherImpactText } from '@/lib/lines';

/** A projection factor as a signed percent: 0.94 -> "−6%". */
export function weatherFactorText(factor: number): string {
  const pct = Math.round((factor - 1) * 100);
  return `${pct >= 0 ? '+' : '−'}${Math.abs(pct)}%`;
}

/** The forecast inside a projection note, "Weather (Rain, 15 mph): x0.94" -> "Rain, 15 mph". */
export function weatherSummary(text: string | null): string | null {
  return text?.match(/\((.*)\):/)?.[1] ?? null;
}

interface WeatherGame {
  game: Game;
  impact: string;
  players: PlayPlayer[];
}

/** This slate's games whose forecast moves projections, with the players it moves most. */
export function weatherGames(games: Game[], players: PlayPlayer[]): WeatherGame[] {
  const teams = new Set(players.map((p) => p.team));
  const seen = new Set<string>();
  return games
    .filter((g) => (teams.has(g.home) || teams.has(g.away)) && !seen.has(g.game_id) && !!seen.add(g.game_id))
    .flatMap((g) => {
      const impact = weatherImpactText(g.weather);
      if (!impact) return [];
      const moved = players
        .filter((p) => p.weather && (p.team === g.home || p.team === g.away))
        .sort((a, b) => Math.abs(b.weather!.factor - 1) - Math.abs(a.weather!.factor - 1));
      return [{ game: g, impact, players: moved }];
    });
}

/**
 * Weather watch: each slate game whose kickoff forecast (wind, rain, snow,
 * cold) moves the projections -- what it does to passing, scoring and DSTs,
 * and the players whose projections it moved most.
 */
export default function WeatherCard({ games }: { games: WeatherGame[] }) {
  const [expanded, setExpanded] = useState(false);
  const style = useExpandedWidth(expanded);
  return (
    <View className="dfs-card" style={style}>
      <Pressable onPress={() => setExpanded((e) => !e)} accessibilityRole="button" aria-expanded={expanded}>
        <Text className="dfs-card-kicker">Weather</Text>
        <Text className="dfs-card-title">
          {games.length} weather {games.length === 1 ? 'game' : 'games'}
        </Text>
        <Text className="dfs-card-subtitle">Kickoff forecasts that move projections -- already built into every player&apos;s projection</Text>
        {games.map(({ game: g, impact, players }) => {
          const shown = expanded ? players : players.slice(0, 3);
          return (
            <View key={g.game_id} className="mt-2">
              <Text className="dfs-preview" numberOfLines={expanded ? undefined : 1}>
                {g.away} @ {g.home}
                {g.weather?.summary ? <Text className="dfs-meta"> · {g.weather.summary}</Text> : null}
              </Text>
              <Text className="upcoming-weather-impact" numberOfLines={expanded ? undefined : 2}>
                {impact}
              </Text>
              {shown.length ? (
                <Text className="dfs-meta" numberOfLines={expanded ? undefined : 2}>
                  {shown.map((p) => `${p.name} (${p.position}) ${weatherFactorText(p.weather!.factor)}`).join(' · ')}
                  {!expanded && players.length > shown.length ? ` · +${players.length - shown.length} more` : ''}
                </Text>
              ) : null}
            </View>
          );
        })}
        <Text className="upcoming-expand-hint">{expanded ? 'Collapse ▲' : 'Tap for every affected player ▼'}</Text>
      </Pressable>
    </View>
  );
}
