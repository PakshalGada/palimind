import { useCallback, useEffect, useState } from 'react';

interface BookmarkableMessage {
  role: string;
  content: string;
}

function signature(msg: BookmarkableMessage): string {
  return `${msg.role}:${(msg.content || '').slice(0, 240)}`;
}

function storageKey(sessionId: string | null): string {
  return `palimind:bookmarks:${sessionId ?? 'none'}`;
}

function load(key: string): Set<string> {
  if (typeof localStorage === 'undefined') return new Set();
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? new Set(parsed.filter((v): v is string => typeof v === 'string')) : new Set();
  } catch {
    return new Set();
  }
}

/**
 * Per-session bookmarks for individual messages. Persisted to localStorage and
 * keyed by a role+content signature so they survive session reloads.
 */
export function useBookmarks(sessionId: string | null) {
  const key = storageKey(sessionId);
  const [bookmarks, setBookmarks] = useState<Set<string>>(() => load(key));

  useEffect(() => {
    setBookmarks(load(key));
  }, [key]);

  const toggle = useCallback(
    (msg: BookmarkableMessage) => {
      setBookmarks((prev) => {
        const next = new Set(prev);
        const sig = signature(msg);
        if (next.has(sig)) next.delete(sig);
        else next.add(sig);
        try {
          localStorage.setItem(key, JSON.stringify([...next]));
        } catch {
          // ignore
        }
        return next;
      });
    },
    [key],
  );

  const isBookmarked = useCallback(
    (msg: BookmarkableMessage) => bookmarks.has(signature(msg)),
    [bookmarks],
  );

  return { isBookmarked, toggle, count: bookmarks.size };
}
