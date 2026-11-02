import type { ToolStep } from '../model';
import { parseOutput } from '../toolOutput';

interface FeedItem {
  title: string;
  date: string;
  url: string;
}

function itemsOf(value: unknown): FeedItem[] {
  if (!value || typeof value !== 'object') return [];
  const record = value as Record<string, unknown>;
  const entries = Array.isArray(record.items)
    ? record.items
    : Array.isArray(record.entries)
      ? record.entries
      : [];
  return entries
    .map((entry) => {
      if (!entry || typeof entry !== 'object') return null;
      const item = entry as Record<string, unknown>;
      const title = typeof item.title === 'string' ? item.title : '';
      if (!title) return null;
      const date =
        (typeof item.published === 'string' && item.published) ||
        (typeof item.date === 'string' && item.date) ||
        '';
      const url = typeof item.link === 'string' ? item.link : '';
      return { title, date, url };
    })
    .filter((item): item is FeedItem => Boolean(item))
    .slice(0, 5);
}

function relative(date: string): string {
  if (!date) return '';
  const parsed = Date.parse(date);
  if (!Number.isFinite(parsed)) return date.slice(0, 10);
  const days = Math.round((Date.now() - parsed) / 86_400_000);
  if (days <= 0) return 'today';
  if (days === 1) return '1d ago';
  if (days < 30) return `${days}d ago`;
  return date.slice(0, 10);
}

export default function FeedBody({ step }: { step: ToolStep }) {
  const value = parseOutput(step.output);
  const feedTitle =
    value && typeof value === 'object' && typeof (value as Record<string, unknown>).title === 'string'
      ? String((value as Record<string, unknown>).title)
      : 'Feed';
  const items = itemsOf(value);
  if (items.length === 0) return <div className="act-empty">No results</div>;
  return (
    <div className="act-body">
      <div className="act-section-title">{feedTitle}</div>
      <div className="act-results">
        {items.map((item, index) => (
          <div key={`${item.title}-${index}`} className="act-result" style={{ paddingBlock: 3 }}>
            <span className="act-result__body">
              <span className="act-result__title">{item.title}</span>
              <span className="act-result__meta">{relative(item.date)}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
