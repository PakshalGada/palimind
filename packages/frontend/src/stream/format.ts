/** 0:05 / 1:02:03 style timestamps for media citations. */
export function formatTimestamp(seconds: number): string {
  const sec = Math.round(seconds);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const r = sec % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
    : `${m}:${String(r).padStart(2, '0')}`;
}

/** Last path segment, used for compact citation chip labels. */
export function baseName(file: string): string {
  return file.split(/[\\/]/).pop() || file;
}
