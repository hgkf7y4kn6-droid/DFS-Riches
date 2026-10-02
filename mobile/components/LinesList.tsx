import { Text, View } from 'react-native';

import { atsCell, finalCell, impliedCell, paceCell, spreadCell, totalCell, totalResultCell, weatherText, type Cell } from '@/lib/lines';

const TONE_CLASS: Record<string, string> = {
  positive: 'text-positive',
  negative: 'text-negative',
  pending: 'text-muted',
  neutral: '',
};

function LinesCell({ label, cell, wide }: { label: string; cell: Cell; wide?: boolean }) {
  return (
    <View className={wide ? 'w-full' : 'lines-cell'}>
      <Text className="lines-label">{label}</Text>
      <Text className={`lines-value ${TONE_CLASS[cell.tone ?? 'neutral']}`}>{cell.text}</Text>
      {cell.sub ? <Text className="lines-sub">{cell.sub}</Text> : null}
    </View>
  );
}

function GameLines({ game }: { game: Game }) {
  return (
    <View className="lines-card">
      <View className="flex-row items-start justify-between">
        <View className="flex-1 pr-2">
          <Text className="game-matchup">
            {game.away} @ {game.home}
          </Text>
          <Text className="game-meta">
            {game.kickoff_et}
            {game.weather ? ` · ${weatherText(game.weather)}` : ''}
          </Text>
        </View>
        <Text className="text-sm font-semibold text-primary">{finalCell(game).text}</Text>
      </View>
      <View className="lines-grid">
        <LinesCell label="Spread" cell={spreadCell(game)} wide />
        <LinesCell label="Total" cell={totalCell(game)} />
        <LinesCell label="Implied totals" cell={impliedCell(game)} />
        <LinesCell label="Vs spread" cell={atsCell(game)} />
        <LinesCell label="Vs total" cell={totalResultCell(game)} />
        <LinesCell label="Pace vs baseline (plays)" cell={paceCell(game)} wide />
      </View>
    </View>
  );
}

/**
 * Lines & Performance as a vertical list: each game's closing spread, total
 * and implied team totals (with each team's trailing L3/L6/L9 averages), and
 * once final, how the result landed against each line and each team's pace.
 */
export default function LinesList({ games }: { games: Game[] }) {
  return (
    <View>
      {games.map((g) => (
        <GameLines key={g.game_id} game={g} />
      ))}
    </View>
  );
}
