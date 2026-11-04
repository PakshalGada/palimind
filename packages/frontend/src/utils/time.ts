/**
 * Relative time for UI metadata. Accepts seconds or milliseconds and returns
 * "just now", "4m ago", "2h ago", "3d ago" or a short date.
 */
export function relativeTime(value: number | null | undefined): string {
  if (!value) return '—';
  const ms = value < 1e12 ? value * 1000 : value;
  const diff = Date.now() - ms;
  if (diff < 45_000) return 'just now';
  const minutes = Math.round(diff / 60_000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(ms).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  });
}

/** Exact timestamp for a `title` attribute. */
export function exactTime(value: number | null | undefined): string {
  if (!value) return '';
  const ms = value < 1e12 ? value * 1000 : value;
  return new Date(ms).toLocaleString();
}

export function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 5) return 'Still up?';
  if (hour < 12) return 'Good morning.';
  if (hour < 18) return 'Good afternoon.';
  return 'Good evening.';
}
