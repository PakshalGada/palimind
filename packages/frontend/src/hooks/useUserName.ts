import { useEffect, useState } from 'react';
import { getUserName, USER_NAME_EVENT } from '../utils/userName';

/** Reads the locally stored name and stays in sync with Settings. */
export function useUserName(): string {
  const [name, setName] = useState(getUserName);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ name?: string }>).detail;
      setName(detail?.name ?? getUserName());
    };
    window.addEventListener(USER_NAME_EVENT, handler);
    return () => window.removeEventListener(USER_NAME_EVENT, handler);
  }, []);

  return name;
}
