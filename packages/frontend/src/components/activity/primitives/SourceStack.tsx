import type { ResultItem } from '../model';
import { Favicon } from './Favicon';

const MAX_VISIBLE = 5;

export function SourceStack({
  items,
  className = '',
}: {
  items: readonly ResultItem[];
  className?: string;
}) {
  if (items.length === 0) return null;
  const visible = items.slice(0, MAX_VISIBLE);
  const extra = items.length - visible.length;
  return (
    <span
      className={`act-source-stack ${className}`.trim()}
      title={items.map((item) => item.domain ?? item.title).join('\n')}
    >
      {visible.map((item, index) => (
        <span
          key={item.id}
          className="act-source-stack__item"
          style={{ zIndex: MAX_VISIBLE - index }}
        >
          <Favicon domain={item.domain} title={item.title} />
        </span>
      ))}
      {extra > 0 && <span className="act-source-stack__more act-tabular">+{extra}</span>}
    </span>
  );
}
