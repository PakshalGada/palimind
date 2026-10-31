/**
 * IndexedDB storage for artifact version bodies.
 *
 * localStorage keeps only metadata (ids, timestamps, notes, sizes). The
 * potentially large version contents live here so long artifacts and dozens
 * of versions do not exhaust the ~5 MB localStorage quota.
 */

const DB_NAME = 'palimind-artifact-vault';
const DB_VERSION = 1;
const CONTENT_STORE = 'version-content';

interface StoredVersionContent {
  id: string;
  artifactId: string;
  content: string;
}

/** Used when IndexedDB is unavailable (SSR, tests, locked-down webviews). */
const memoryContents = new Map<string, string>();

let dbPromise: Promise<IDBDatabase | null> | null = null;

function openDb(): Promise<IDBDatabase | null> {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise(resolve => {
    if (typeof indexedDB === 'undefined') {
      resolve(null);
      return;
    }
    try {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(CONTENT_STORE)) {
          db.createObjectStore(CONTENT_STORE, { keyPath: 'id' });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
      request.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });

  return dbPromise;
}

function txDone(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

export async function putVersionContents(
  entries: StoredVersionContent[],
): Promise<void> {
  if (entries.length === 0) return;
  for (const entry of entries) memoryContents.set(entry.id, entry.content);

  const db = await openDb();
  if (!db) return;
  try {
    const tx = db.transaction(CONTENT_STORE, 'readwrite');
    const store = tx.objectStore(CONTENT_STORE);
    for (const entry of entries) store.put(entry);
    await txDone(tx);
  } catch {
    // The in-memory copy above keeps the session usable.
  }
}

export async function getVersionContents(
  ids: string[],
): Promise<Map<string, string>> {
  const result = new Map<string, string>();
  const missing: string[] = [];

  for (const id of ids) {
    const cached = memoryContents.get(id);
    if (cached !== undefined) result.set(id, cached);
    else missing.push(id);
  }
  if (missing.length === 0) return result;

  const db = await openDb();
  if (!db) return result;

  try {
    const tx = db.transaction(CONTENT_STORE, 'readonly');
    const store = tx.objectStore(CONTENT_STORE);
    await new Promise<void>(resolve => {
      let remaining = missing.length;
      const finish = () => {
        remaining -= 1;
        if (remaining === 0) resolve();
      };
      for (const id of missing) {
        const request = store.get(id);
        request.onsuccess = () => {
          const value = request.result as StoredVersionContent | undefined;
          if (value && typeof value.content === 'string') {
            memoryContents.set(id, value.content);
            result.set(id, value.content);
          }
          finish();
        };
        request.onerror = finish;
      }
    });
  } catch {
    // Ignore and return whatever the memory cache had.
  }

  return result;
}

export async function deleteVersionContents(ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  for (const id of ids) memoryContents.delete(id);

  const db = await openDb();
  if (!db) return;
  try {
    const tx = db.transaction(CONTENT_STORE, 'readwrite');
    const store = tx.objectStore(CONTENT_STORE);
    for (const id of ids) store.delete(id);
    await txDone(tx);
  } catch {
    // Best effort.
  }
}
