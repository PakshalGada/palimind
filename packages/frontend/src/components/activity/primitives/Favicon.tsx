import { useState } from 'react';
import { Icon } from '../icons';

const failed = new Set<string>();

function faviconUrl(domain: string): string {
  return `https://icons.duckduckgo.com/ip3/${domain}.ico`;
}

export function Favicon({
  domain,
  title,
  size = 16,
}: {
  domain?: string;
  title?: string;
  size?: number;
}) {
  const clean = domain?.replace(/^www\./, '') ?? '';
  const [broken, setBroken] = useState(() => !clean || failed.has(clean));
  const showImage = Boolean(clean) && !broken;
  return (
    <span
      className="act-favicon"
      title={title ?? clean}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {showImage ? (
        <img
          src={faviconUrl(clean)}
          alt=""
          width={size}
          height={size}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => {
            failed.add(clean);
            setBroken(true);
          }}
        />
      ) : (
        <Icon name="globe" size={Math.max(10, size - 4)} />
      )}
    </span>
  );
}
