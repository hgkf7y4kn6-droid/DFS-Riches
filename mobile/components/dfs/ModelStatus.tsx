import { Text } from 'react-native';

import { SkeletonCards } from '@/components/Skeleton';
import StatusView from '@/components/StatusView';
import { useDfsModel } from '@/lib/dfs-model-context';

/** Loading / error / unavailable states shared by the DFS Model, Cash and GPP tabs. */
export default function ModelStatus() {
  const { model, loading, error, refresh } = useDfsModel();
  if (loading && !model) {
    return (
      <>
        <Text className="empty-text">Building the model for this slate -- this can take a few seconds.</Text>
        <SkeletonCards count={2} />
      </>
    );
  }
  if (error) return <StatusView error={error} onRetry={refresh} />;
  if (model && !model.available) return <Text className="home-empty-state">{model.reason ?? 'The DFS model is not available for this slate yet.'}</Text>;
  return null;
}
