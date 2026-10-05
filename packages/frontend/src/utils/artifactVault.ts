import type { Artifact, ArtifactType } from './artifacts';

const VAULT_KEY = 'palimind:artifacts';

export interface SavedArtifact {
  id: string;
  type: ArtifactType;
  language: string;
  title: string;
  content: string;
  savedAt: number;
}

export function loadVault(): SavedArtifact[] {
  if (typeof localStorage === 'undefined') return [];
  try {
    const raw = localStorage.getItem(VAULT_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (a): a is SavedArtifact =>
        Boolean(a) && typeof (a as SavedArtifact).id === 'string' && typeof (a as SavedArtifact).content === 'string',
    );
  } catch {
    return [];
  }
}

function persist(items: SavedArtifact[]): void {
  try {
    localStorage.setItem(VAULT_KEY, JSON.stringify(items));
  } catch {
    // ignore quota / unavailable storage
  }
}

export function saveToVault(artifact: Pick<Artifact, 'id' | 'type' | 'language' | 'title' | 'content'>): SavedArtifact[] {
  const existing = loadVault().filter((a) => a.id !== artifact.id);
  const saved: SavedArtifact = {
    id: artifact.id,
    type: artifact.type,
    language: artifact.language,
    title: artifact.title,
    content: artifact.content,
    savedAt: Date.now(),
  };
  const next = [saved, ...existing];
  persist(next);
  return next;
}

export function removeFromVault(id: string): SavedArtifact[] {
  const next = loadVault().filter((a) => a.id !== id);
  persist(next);
  return next;
}
