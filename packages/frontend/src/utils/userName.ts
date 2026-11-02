const STORAGE_KEY = 'palimind:user-name';

/** Broadcast so every mounted greeting updates without a page reload. */
export const USER_NAME_EVENT = 'palimind:user-name';

export function getUserName(): string {
  try {
    return (localStorage.getItem(STORAGE_KEY) ?? '').trim().slice(0, 40);
  } catch {
    return '';
  }
}

export function setUserName(name: string): void {
  const clean = name.trim().slice(0, 40);
  try {
    if (clean) localStorage.setItem(STORAGE_KEY, clean);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* localStorage can be unavailable in hardened environments */
  }
  window.dispatchEvent(new CustomEvent(USER_NAME_EVENT, { detail: { name: clean } }));
}
