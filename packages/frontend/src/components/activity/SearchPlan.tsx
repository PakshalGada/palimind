import type { SearchAspect, SearchState } from './model';
import { StatusIcon } from './primitives/StatusIcon';

function statusFor(aspect: SearchAspect): 'pending' | 'running' | 'success' | 'error' {
  if (aspect.status === 'done') return 'success';
  if (aspect.status === 'gap') return 'error';
  if (aspect.status === 'searching') return 'running';
  return 'pending';
}

function statusLabel(aspect: SearchAspect): string {
  if (aspect.status === 'done') return 'covered';
  if (aspect.status === 'gap') return 'no source';
  if (aspect.status === 'searching') return 'searching';
  return 'queued';
}

/**
 * The live decomposition of a web search: intent, sub-questions, coverage and
 * how many sources each one produced. Rendered inside the activity panel so it
 * is visible in every chat mode.
 */
export function SearchPlan({ search }: { search: SearchState }) {
  if (search.aspects.length === 0 && !search.intent) return null;

  const covered = search.aspects.filter((aspect) => aspect.status === 'done').length;
  const total = search.aspects.length;
  const details = [
    search.intent && `intent: ${search.intent}`,
    search.freshness && search.freshness !== 'any' ? `freshness: ${search.freshness}` : '',
    search.entities.length > 0 ? `entities: ${search.entities.slice(0, 3).join(', ')}` : '',
  ].filter(Boolean);

  return (
    <div className="act-search">
      <div className="act-search__head">
        <span className="act-search__title">Web search</span>
        <span className="act-search__meta act-muted act-tabular">
          {total > 0 ? `${covered}/${total} aspects` : 'planning'}
          {search.sources > 0 && ` · ${search.sources} sources`}
          {search.queries > 0 && ` · ${search.queries} queries`}
          {search.gaps.length > 0 && ` · ${search.gaps.length} gap${search.gaps.length === 1 ? '' : 's'}`}
        </span>
      </div>

      {details.length > 0 && (
        <div className="act-search__intent act-muted">{details.join(' · ')}</div>
      )}

      <ul className="act-search__aspects">
        {search.aspects.map((aspect) => (
          <li
            key={aspect.id}
            className={`act-search__aspect act-search__aspect--${aspect.status}`}
          >
            <StatusIcon status={statusFor(aspect)} size={12} animate={aspect.status === 'searching'} />
            <span className="act-search__question" title={aspect.queries.join(' · ')}>
              {aspect.title || aspect.question}
            </span>
            {aspect.sourceCount > 0 && (
              <span className="act-chip act-tabular">{aspect.sourceCount}</span>
            )}
            <span className="act-search__status act-muted">{statusLabel(aspect)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
