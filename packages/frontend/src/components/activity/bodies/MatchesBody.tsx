import type { ToolStep } from '../model';
import { Icon } from '../icons';
import { Highlight } from '../primitives/Highlight';
import { parseOutput } from '../toolOutput';

const LIMIT = 20;

interface Match {
  file: string;
  line?: number;
  text: string;
}

function argString(args: unknown, key: string): string {
  if (!args || typeof args !== 'object') return '';
  const value = (args as Record<string, unknown>)[key];
  return typeof value === 'string' ? value : '';
}

function matchesOf(value: unknown): Match[] {
  const matches: Match[] = [];
  if (typeof value === 'string') {
    for (const line of value.split('\n')) {
      const match = line.match(/^(.*?):(\d+):\s?(.*)$/);
      if (match) matches.push({ file: match[1], line: Number(match[2]), text: match[3] });
    }
    return matches;
  }
  if (!value || typeof value !== 'object') return matches;
  const record = value as Record<string, unknown>;
  const raw = Array.isArray(record.matches)
    ? record.matches
    : Array.isArray(record.results)
      ? record.results
      : [];
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue;
    const item = entry as Record<string, unknown>;
    const file =
      typeof item.file === 'string' ? item.file : typeof item.path === 'string' ? item.path : '';
    const text =
      typeof item.text === 'string' ? item.text : typeof item.line === 'string' ? item.line : '';
    if (!text) continue;
    matches.push({
      file,
      line: typeof item.line === 'number' ? item.line : undefined,
      text,
    });
  }
  return matches;
}

export default function MatchesBody({ step }: { step: ToolStep }) {
  const pattern = argString(step.args, 'pattern') || argString(step.args, 'query');
  const matches = matchesOf(parseOutput(step.output)).slice(0, LIMIT);
  if (matches.length === 0) return <div className="act-empty">No results</div>;
  const groups = new Map<string, Match[]>();
  for (const match of matches) {
    const key = match.file || 'Matches';
    const group = groups.get(key) ?? [];
    group.push(match);
    groups.set(key, group);
  }
  return (
    <div className="act-body act-body--flush">
      {[...groups.entries()].map(([file, group]) => (
        <div key={file} style={{ marginBottom: 8 }}>
          <div className="act-section-title">
            <Icon name="file" size={12} />
            <span>{file}</span>
            <span className="act-tabular">{group.length}</span>
          </div>
          <div className="act-tree">
            {group.map((match, index) => (
              <div key={index} className="act-tree__row">
                <span className="act-tabular act-muted" style={{ minWidth: 28, textAlign: 'end' }}>
                  {match.line ?? ''}
                </span>
                <span>
                  <Highlight text={match.text} terms={[pattern]} />
                </span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
