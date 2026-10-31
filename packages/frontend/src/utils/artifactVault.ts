import type { Artifact, ArtifactType } from './artifacts';
import {
  deleteVersionContents,
  getVersionContents,
  putVersionContents,
} from './artifactVaultDb.ts';

/**
 * Local artifact vault.
 *
 * localStorage only stores lightweight metadata; version bodies live in
 * IndexedDB (see `artifactVaultDb.ts`). Legacy vaults that stored contents in
 * localStorage are migrated automatically on first load.
 */

const VAULT_KEY = 'palimind:artifacts';
const MAX_VERSIONS = 40;

export interface ArtifactVersionRecord {
  id: string;
  artifactId: string;
  savedAt: number;
  note?: string;
  /** Content length at save time, so the timeline can show size without loading. */
  size: number;
  /** True for automatic snapshots (before restore / closing the editor). */
  autosaved?: boolean;
}

export interface SavedArtifactMeta {
  id: string;
  type: ArtifactType;
  language: string;
  title: string;
  savedAt: number;
  currentVersionId: string;
  versions: ArtifactVersionRecord[];
}

export interface SavedArtifact extends SavedArtifactMeta {
  /** Content of `currentVersionId`, loaded from IndexedDB. */
  content: string;
}

export interface SaveDraftResult {
  items: SavedArtifact[];
  versionId: string;
  created: boolean;
}

function newVersionId(artifactId: string): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${artifactId}:${crypto.randomUUID()}`;
  }
  return `${artifactId}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}

function asType(value: unknown): ArtifactType {
  return typeof value === 'string' ? (value as ArtifactType) : 'code';
}

function readRaw(): unknown {
  if (typeof localStorage === 'undefined') return null;
  try {
    const raw = localStorage.getItem(VAULT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function persistMeta(items: SavedArtifactMeta[]): void {
  if (typeof localStorage === 'undefined') return;
  try {
    // Explicitly strip contents in case a caller passed a hydrated record.
    const meta = items.map(item => ({
      id: item.id,
      type: item.type,
      language: item.language,
      title: item.title,
      savedAt: item.savedAt,
      currentVersionId: item.currentVersionId,
      versions: item.versions.map(version => ({
        id: version.id,
        artifactId: version.artifactId,
        savedAt: version.savedAt,
        note: version.note,
        size: version.size,
        autosaved: version.autosaved,
      })),
    }));
    localStorage.setItem(VAULT_KEY, JSON.stringify(meta));
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('palimind:artifact-vault-updated'));
    }
  } catch {
    // Quota / unavailable storage: the in-memory session still works.
  }
}

function normalizeMeta(raw: unknown[]): SavedArtifactMeta[] {
  const out: SavedArtifactMeta[] = [];
  for (const value of raw) {
    if (!value || typeof value !== 'object') continue;
    const item = value as Record<string, unknown>;
    if (typeof item.id !== 'string' || !item.id) continue;

    const versions: ArtifactVersionRecord[] = [];
    if (Array.isArray(item.versions)) {
      for (const candidate of item.versions) {
        if (!candidate || typeof candidate !== 'object') continue;
        const version = candidate as Record<string, unknown>;
        if (typeof version.id !== 'string' || !version.id) continue;
        versions.push({
          id: version.id,
          artifactId:
            typeof version.artifactId === 'string' ? version.artifactId : item.id,
          savedAt:
            typeof version.savedAt === 'number' ? version.savedAt : Date.now(),
          note: typeof version.note === 'string' ? version.note : undefined,
          size: typeof version.size === 'number' ? version.size : 0,
          autosaved: version.autosaved === true,
        });
      }
    }
    if (versions.length === 0) continue;

    const currentVersionId =
      typeof item.currentVersionId === 'string' &&
      versions.some(version => version.id === item.currentVersionId)
        ? item.currentVersionId
        : versions[versions.length - 1].id;

    out.push({
      id: item.id,
      type: asType(item.type),
      language: typeof item.language === 'string' ? item.language : '',
      title:
        typeof item.title === 'string' && item.title.trim()
          ? item.title
          : 'Artifact',
      savedAt: typeof item.savedAt === 'number' ? item.savedAt : Date.now(),
      currentVersionId,
      versions,
    });
  }
  return out;
}

interface LegacyVersion {
  id?: unknown;
  content?: unknown;
  savedAt?: unknown;
  note?: unknown;
  size?: unknown;
  autosaved?: unknown;
}

interface LegacyArtifact extends Record<string, unknown> {
  id?: unknown;
  content?: unknown;
  versions?: unknown;
  currentVersionId?: unknown;
  type?: unknown;
  language?: unknown;
  title?: unknown;
  savedAt?: unknown;
}

function isLegacy(raw: unknown[]): boolean {
  return raw.some(value => {
    if (!value || typeof value !== 'object') return false;
    const item = value as LegacyArtifact;
    if (typeof item.content === 'string') return true;
    return (
      Array.isArray(item.versions) &&
      item.versions.some(
        version =>
          version &&
          typeof version === 'object' &&
          typeof (version as LegacyVersion).content === 'string',
      )
    );
  });
}

/** Convert a localStorage-era record into metadata + IndexedDB bodies. */
function migrateLegacy(raw: unknown[]): {
  meta: SavedArtifactMeta[];
  contents: { id: string; artifactId: string; content: string }[];
} {
  const meta: SavedArtifactMeta[] = [];
  const contents: { id: string; artifactId: string; content: string }[] = [];
  const now = Date.now();

  for (const value of raw) {
    if (!value || typeof value !== 'object') continue;
    const item = value as LegacyArtifact;
    if (typeof item.id !== 'string' || !item.id) continue;

    const versions: ArtifactVersionRecord[] = [];
    if (Array.isArray(item.versions)) {
      for (const candidate of item.versions) {
        if (!candidate || typeof candidate !== 'object') continue;
        const version = candidate as LegacyVersion;
        const id =
          typeof version.id === 'string' && version.id
            ? version.id
            : newVersionId(item.id);
        const hasContent = typeof version.content === 'string';
        const content = hasContent ? (version.content as string) : '';
        versions.push({
          id,
          artifactId: item.id,
          savedAt:
            typeof version.savedAt === 'number' ? version.savedAt : now,
          note: typeof version.note === 'string' ? version.note : undefined,
          size: hasContent
            ? content.length
            : typeof version.size === 'number'
              ? version.size
              : 0,
          autosaved: version.autosaved === true,
        });
        // Only write bodies that were actually stored in localStorage. A
        // metadata-only record may already have its body in IndexedDB.
        if (hasContent) {
          contents.push({ id, artifactId: item.id, content });
        }
      }
    }

    let currentVersionId =
      typeof item.currentVersionId === 'string' ? item.currentVersionId : '';
    const currentContent =
      typeof item.content === 'string' ? item.content : undefined;

    if (versions.length === 0) {
      if (currentContent === undefined) continue;
      const id = currentVersionId || newVersionId(item.id);
      currentVersionId = id;
      versions.push({
        id,
        artifactId: item.id,
        savedAt: now,
        note: 'Initial save',
        size: currentContent.length,
      });
      contents.push({ id, artifactId: item.id, content: currentContent });
    } else {
      if (!versions.some(version => version.id === currentVersionId)) {
        currentVersionId = versions[versions.length - 1].id;
      }
      if (currentContent !== undefined) {
        // The legacy top-level content is the authoritative current value.
        const entry = contents.find(candidate => candidate.id === currentVersionId);
        if (entry) entry.content = currentContent;
        else {
          contents.push({
            id: currentVersionId,
            artifactId: item.id,
            content: currentContent,
          });
        }
      }
    }

    meta.push({
      id: item.id,
      type: asType(item.type),
      language: typeof item.language === 'string' ? item.language : '',
      title:
        typeof item.title === 'string' && item.title.trim()
          ? item.title
          : 'Artifact',
      savedAt: typeof item.savedAt === 'number' ? item.savedAt : now,
      currentVersionId,
      versions,
    });
  }

  return { meta, contents };
}

async function loadVaultMeta(): Promise<SavedArtifactMeta[]> {
  const raw = readRaw();
  if (!Array.isArray(raw)) return [];

  if (isLegacy(raw)) {
    const { meta, contents } = migrateLegacy(raw);
    await putVersionContents(contents);
    persistMeta(meta);
    return meta;
  }

  return normalizeMeta(raw);
}

/** Hydrate every metadata record with its current version content. */
export async function loadVault(): Promise<SavedArtifact[]> {
  const meta = await loadVaultMeta();
  const contents = await getVersionContents(
    meta.map(item => item.currentVersionId),
  );
  return meta.map(item => ({
    ...item,
    content: contents.get(item.currentVersionId) ?? '',
  }));
}

export async function getSavedArtifact(id: string): Promise<SavedArtifact | null> {
  const items = await loadVault();
  return items.find(item => item.id === id) || null;
}

/** Read one historical version body (used by the compare view). */
export async function getVaultVersionContent(
  artifactId: string,
  versionId: string,
): Promise<string | null> {
  const meta = await loadVaultMeta();
  const artifact = meta.find(item => item.id === artifactId);
  if (!artifact?.versions.some(version => version.id === versionId)) return null;
  const contents = await getVersionContents([versionId]);
  return contents.get(versionId) ?? null;
}

interface WriteOptions {
  note?: string;
  autosaved?: boolean;
  /** When false, always create a version even if content is unchanged. */
  dedupe?: boolean;
}

interface WriteResult {
  metas: SavedArtifactMeta[];
  versionId: string;
  created: boolean;
}

/**
 * Serialize metadata mutations so a save, autosave and restore cannot clobber
 * each other while IndexedDB writes are in flight.
 */
let writeQueue: Promise<unknown> = Promise.resolve();

function enqueue<T>(task: () => Promise<T>): Promise<T> {
  const next = writeQueue.then(task, task);
  writeQueue = next.then(
    () => undefined,
    () => undefined,
  );
  return next;
}

async function writeVersion(
  artifact: Pick<Artifact, 'id' | 'type' | 'language' | 'title' | 'content'>,
  options: WriteOptions,
): Promise<WriteResult> {
  const metas = await loadVaultMeta();
  const existing = metas.find(item => item.id === artifact.id);

  if (existing && options.dedupe !== false) {
    const current = (
      await getVersionContents([existing.currentVersionId])
    ).get(existing.currentVersionId);
    if (current === artifact.content) {
      return {
        metas,
        versionId: existing.currentVersionId,
        created: false,
      };
    }
  }

  const now = Date.now();
  const versionId = newVersionId(artifact.id);
  const version: ArtifactVersionRecord = {
    id: versionId,
    artifactId: artifact.id,
    savedAt: now,
    note: options.note,
    size: artifact.content.length,
    autosaved: options.autosaved,
  };

  let versions = [...(existing?.versions ?? []), version];
  const evicted =
    versions.length > MAX_VERSIONS
      ? versions.slice(0, versions.length - MAX_VERSIONS)
      : [];
  versions = versions.slice(-MAX_VERSIONS);

  await putVersionContents([
    { id: versionId, artifactId: artifact.id, content: artifact.content },
  ]);
  if (evicted.length > 0) {
    await deleteVersionContents(evicted.map(item => item.id));
  }

  const meta: SavedArtifactMeta = {
    id: artifact.id,
    type: artifact.type,
    language: artifact.language,
    title: artifact.title,
    savedAt: now,
    currentVersionId: versionId,
    versions,
  };
  const next = [meta, ...metas.filter(item => item.id !== artifact.id)];
  persistMeta(next);

  return { metas: next, versionId, created: true };
}

export interface SaveToVaultResult {
  items: SavedArtifact[];
  versionId: string;
  created: boolean;
}

export async function saveToVault(
  artifact: Pick<Artifact, 'id' | 'type' | 'language' | 'title' | 'content'>,
  note = 'Saved from artifact panel',
): Promise<SaveToVaultResult> {
  const result = await enqueue(() => writeVersion(artifact, { note }));
  return {
    items: await loadVault(),
    versionId: result.versionId,
    created: result.created,
  };
}

/**
 * Save an automatic snapshot. Returns the version that is current after the
 * call, which lets "Undo restore" return to the exact pre-restore draft.
 */
export async function saveDraft(
  artifact: Pick<Artifact, 'id' | 'type' | 'language' | 'title' | 'content'>,
  note = 'Autosaved draft',
): Promise<SaveDraftResult> {
  const result = await enqueue(() =>
    writeVersion(artifact, { note, autosaved: true }),
  );
  return {
    items: await loadVault(),
    versionId: result.versionId,
    created: result.created,
  };
}

export async function removeFromVault(id: string): Promise<SavedArtifact[]> {
  await enqueue(async () => {
    const metas = await loadVaultMeta();
    const target = metas.find(item => item.id === id);
    if (target) {
      await deleteVersionContents(target.versions.map(version => version.id));
    }
    persistMeta(metas.filter(item => item.id !== id));
  });
  return loadVault();
}

/** Point the artifact at an existing version without duplicating history. */
export async function restoreVaultVersion(
  id: string,
  versionId: string,
): Promise<SavedArtifact[]> {
  await enqueue(async () => {
    const metas = await loadVaultMeta();
    const next = metas.map(item => {
      if (item.id !== id) return item;
      if (!item.versions.some(version => version.id === versionId)) return item;
      return {
        ...item,
        currentVersionId: versionId,
        savedAt: Date.now(),
      };
    });
    persistMeta(next);
  });
  return loadVault();
}

export async function renameVaultArtifact(
  id: string,
  title: string,
): Promise<SavedArtifact[]> {
  await enqueue(async () => {
    const metas = await loadVaultMeta();
    persistMeta(
      metas.map(item =>
        item.id === id
          ? { ...item, title: title.trim() || item.title }
          : item,
      ),
    );
  });
  return loadVault();
}
