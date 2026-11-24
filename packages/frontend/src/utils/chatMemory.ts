export type ChatMemoryScope = 'chat' | 'project' | 'global';

export interface ChatMemoryEntry {
  id: string;
  scope: ChatMemoryScope;
  scopeId: string;
  text: string;
  createdAt: number;
}

const STORAGE_KEY = 'palimind:chat-memory-v2';
const LEGACY_KEY = 'palimind:chat-memory';

function makeId(): string {
  return `mem-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function loadChatMemory(): ChatMemoryEntry[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed
          .filter((item) => item && typeof item.text === 'string')
          .map((item) => ({
            id: String(item.id || makeId()),
            scope: item.scope === 'project' || item.scope === 'chat' ? item.scope : 'global',
            scopeId: String(item.scopeId || ''),
            text: String(item.text).slice(0, 500),
            createdAt: Number(item.createdAt) || Date.now(),
          }));
      }
    }
    // Migrate the original flat string list into global memory.
    const legacy = JSON.parse(localStorage.getItem(LEGACY_KEY) || '[]');
    if (Array.isArray(legacy)) {
      return legacy
        .filter((item) => typeof item === 'string' && item.trim())
        .map((text) => ({
          id: makeId(),
          scope: 'global' as const,
          scopeId: '',
          text: text.slice(0, 500),
          createdAt: Date.now(),
        }));
    }
  } catch {
    // storage is optional
  }
  return [];
}

export function saveChatMemory(entries: ChatMemoryEntry[]): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
    localStorage.removeItem(LEGACY_KEY);
  } catch {
    // storage is optional
  }
}

export function makeMemoryEntry(
  text: string,
  scope: ChatMemoryScope,
  scopeId: string,
): ChatMemoryEntry {
  return {
    id: makeId(),
    scope,
    scopeId: scope === 'global' ? '' : scopeId,
    text: text.trim().slice(0, 500),
    createdAt: Date.now(),
  };
}

export function memoryForScope(
  entries: ChatMemoryEntry[],
  { sessionId, projectId }: { sessionId: string | null; projectId: string | null },
): ChatMemoryEntry[] {
  return entries.filter((entry) => {
    if (entry.scope === 'global') return true;
    if (entry.scope === 'project') return Boolean(projectId) && entry.scopeId === projectId;
    return entry.scopeId === (sessionId ?? 'draft');
  });
}

export function searchMemory(entries: ChatMemoryEntry[], query: string): ChatMemoryEntry[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return entries;
  return entries.filter((entry) => entry.text.toLowerCase().includes(needle));
}
