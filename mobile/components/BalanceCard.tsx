import { Pressable, Text, View } from 'react-native';

import { stats } from '@/lib/submissions';
import { useSubmissions } from '@/lib/submissions-context';
import { formatCurrency, formatPercent, formatSignedCurrency } from '@/lib/utils';

/**
 * Money spent on lineup submissions (every logged entry fee), with
 * winnings, net profit/loss on settled contests and win percentage.
 */
export default function BalanceCard({ onLogEntry }: { onLogEntry: () => void }) {
  const { submissions } = useSubmissions();
  const s = stats(submissions);
  const netClass = s.net > 0 ? 'home-balance-positive' : s.net < 0 ? 'home-balance-negative' : '';

  return (
    <View className="home-balance-card">
      <View className="home-balance-header">
        <View>
          <Text className="home-balance-label">Spent on lineup submissions</Text>
          <Text className="home-balance-amount">{formatCurrency(s.spent)}</Text>
          <Text className="home-balance-caption">
            {s.entries} entr{s.entries === 1 ? 'y' : 'ies'} · {s.pending} pending
          </Text>
        </View>
        <Pressable className="home-balance-action" onPress={onLogEntry} accessibilityRole="button" accessibilityLabel="Log a contest entry">
          <Text className="home-balance-action-text">+ Log entry</Text>
        </Pressable>
      </View>
      <View className="home-balance-row">
        <View className="home-balance-stat">
          <Text className="home-balance-stat-value">{formatCurrency(s.won)}</Text>
          <Text className="home-balance-stat-label">Won</Text>
        </View>
        <View className="home-balance-stat">
          <Text className={`home-balance-stat-value ${netClass}`}>{formatSignedCurrency(s.net)}</Text>
          <Text className="home-balance-stat-label">Net P/L</Text>
        </View>
        <View className="home-balance-stat">
          <Text className="home-balance-stat-value">{formatPercent(s.winPct)}</Text>
          <Text className="home-balance-stat-label">Win %</Text>
        </View>
      </View>
    </View>
  );
}
