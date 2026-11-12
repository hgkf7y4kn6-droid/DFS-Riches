import { Text, View } from 'react-native';

import { stats } from '@/lib/submissions';
import { useSubmissions } from '@/lib/submissions-context';
import { formatCurrency, formatPercent, formatSignedCurrency } from '@/lib/utils';

/** The balance card's bottom row: winnings, net profit/loss and win % from logged entries. */
export default function BalanceStats() {
  const { submissions } = useSubmissions();
  const s = stats(submissions);
  const netClass = s.net > 0 ? 'home-balance-positive' : s.net < 0 ? 'home-balance-negative' : '';
  return (
    <View className="home-balance-stats">
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
      <View className="home-balance-stat">
        <Text className="home-balance-stat-value">{s.pending}</Text>
        <Text className="home-balance-stat-label">Pending</Text>
      </View>
    </View>
  );
}
