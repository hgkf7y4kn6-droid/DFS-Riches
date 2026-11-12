import { cssInterop } from 'nativewind';
import { SafeAreaView as RNSafeAreaView } from 'react-native-safe-area-context';

// react-native-safe-area-context's SafeAreaView with NativeWind className
// support (core components get it automatically; third-party ones need this).
cssInterop(RNSafeAreaView, { className: 'style' });

export default RNSafeAreaView;
