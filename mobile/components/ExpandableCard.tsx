import { useState, type ReactNode } from 'react';
import { Image, Pressable, Text, View } from 'react-native';

import icons from '@/constants/icons';
import { colors } from '@/constants/theme';

interface Props {
  title: string;
  subtitle?: string;
  /** Short summary shown on the right of the header (e.g. "16 games"). */
  aside?: string;
  defaultExpanded?: boolean;
  /** Controlled mode: pass both to open/close the card from outside. */
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  /** Shown only while collapsed, under the header. */
  preview?: ReactNode;
  children: ReactNode;
}

/** A section card whose body opens and closes when its header is tapped. */
export default function ExpandableCard({
  title,
  subtitle,
  aside,
  defaultExpanded = false,
  expanded: controlled,
  onExpandedChange,
  preview,
  children,
}: Props) {
  const [uncontrolled, setUncontrolled] = useState(defaultExpanded);
  const expanded = controlled ?? uncontrolled;
  const toggle = () => (onExpandedChange ? onExpandedChange(!expanded) : setUncontrolled(!expanded));
  return (
    <View className="section card">
      <Pressable
        className="expand-header"
        onPress={toggle}
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        accessibilityLabel={`${title}, ${expanded ? 'collapse' : 'expand'}`}>
        <View className="flex-1 pr-3">
          <Text className="section-title">{title}</Text>
          {subtitle ? <Text className="section-subtitle">{subtitle}</Text> : null}
        </View>
        {aside ? <Text className="section-aside">{aside}</Text> : null}
        <Image
          source={icons.chevron}
          className="expand-icon"
          style={{ width: 16, height: 16, tintColor: colors.primary, transform: [{ rotate: expanded ? '180deg' : '0deg' }] }}
        />
      </Pressable>
      {expanded ? <View className="mt-3">{children}</View> : preview ? <View className="mt-3">{preview}</View> : null}
    </View>
  );
}
