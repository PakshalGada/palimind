import type { CSSProperties } from 'react';
import type { BotOptions } from './index';

export interface BotAvatarProps extends BotOptions {
  className?: string;
  style?: CSSProperties;
  onPoke?: (e: Event) => void;
}
export declare function BotAvatar(props: BotAvatarProps): JSX.Element;
export default BotAvatar;
