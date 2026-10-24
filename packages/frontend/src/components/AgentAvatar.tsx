import BotAvatarCanvas from './BotAvatarCanvas';
import type { BotAvatarConfig, BotState } from '../bots/config';

/**
 * Agent avatar rendered by the vendored "bots" library: an animated, plush
 * 3D-style canvas bot. Uploaded images are still supported.
 */
export default function AgentAvatar({
  config,
  size = 32,
  type = 'bot',
  upload,
  state = 'default',
  interactive = true,
  paused = false,
}: {
  config?: BotAvatarConfig;
  size?: number;
  type?: 'bot' | 'upload' | string;
  upload?: string;
  state?: BotState;
  interactive?: boolean;
  paused?: boolean;
}) {
  if (type === 'upload' && upload) {
    return (
      <span className="agent-avatar agent-avatar--upload" style={{ width: size, height: size }}>
        <img className="agent-avatar__img" src={upload} alt="" />
      </span>
    );
  }

  return (
    <span className={`agent-avatar bot-avatar${paused ? ' bot-avatar--static' : ''}`} style={{ width: size, height: size }}>
      <BotAvatarCanvas
        config={config || {}}
        size={size}
        state={state}
        interactive={interactive}
        paused={paused}
      />
    </span>
  );
}
