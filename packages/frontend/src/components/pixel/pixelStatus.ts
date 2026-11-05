import type { PixelSprite } from './sprites';

/**
 * One pixel shape per status. No rings or plain dots: the mark itself should
 * communicate the state even when animation is paused.
 */
export function pixelForStatus(status: string): PixelSprite {
  switch (status) {
    case 'working':
    case 'running':
      return 'checker';
    case 'waiting':
    case 'awaiting_approval':
      return 'diamond';
    case 'error':
    case 'denied':
      return 'cross';
    case 'paused':
    case 'cancelled':
    case 'stopped':
      return 'pause';
    case 'scheduled':
      return 'clock';
    case 'success':
    case 'completed':
      return 'check';
    default:
      return 'tick';
  }
}
