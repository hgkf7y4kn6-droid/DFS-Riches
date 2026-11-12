import { useWindowDimensions } from 'react-native';

/** Expanded cards in a horizontal list widen to the screen width (minus the 20px gutters). */
export function useExpandedWidth(expanded: boolean, fullWidth = false) {
  const { width } = useWindowDimensions();
  return expanded && !fullWidth ? { width: width - 40 } : undefined;
}
