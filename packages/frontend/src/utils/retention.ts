export const RETENTION_OPTIONS = [0, 7, 30, 90] as const;

export type RetentionDays = (typeof RETENTION_OPTIONS)[number];

export function retentionLabel(days: number): string {
  if (!days) return 'Keep until I delete';
  return `Keep for ${days} days`;
}

export function retentionKey(sessionId: string | null): string {
  return `palimind:chat-retention:${sessionId ?? 'new'}`;
}

export function loadRetention(sessionId: string | null): RetentionDays {
  try {
    const value = Number(localStorage.getItem(retentionKey(sessionId)) || 0);
    return (RETENTION_OPTIONS as readonly number[]).includes(value)
      ? (value as RetentionDays)
      : 0;
  } catch {
    return 0;
  }
}

export function saveRetention(sessionId: string | null, days: RetentionDays): void {
  try {
    localStorage.setItem(retentionKey(sessionId), String(days));
  } catch {
    // storage is optional
  }
}

export function isRetentionExpired(
  sessionId: string | null,
  messages: { timestamp?: number }[],
  now = Date.now(),
): boolean {
  const days = loadRetention(sessionId);
  if (!days) return false;
  const last = messages.reduce((latest, message) => Math.max(latest, message.timestamp || 0), 0);
  if (!last) return false;
  return now - last > days * 24 * 60 * 60 * 1000;
}
