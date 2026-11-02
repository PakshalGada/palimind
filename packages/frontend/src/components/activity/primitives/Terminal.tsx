import { useCallback, useState, useSyncExternalStore } from 'react';
import type { StreamBuffer } from '../buffers';
import { CopyButton } from './CopyButton';

const ANSI_ESCAPE = String.fromCharCode(27);
const ANSI_RE = new RegExp(
  `[${ANSI_ESCAPE}\\u009B][[\\]()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]`,
  'g',
);

function stripAnsi(value: string): string {
  return value.replace(ANSI_RE, '');
}

function BufferBody({ buffer }: { buffer: StreamBuffer }) {
  const subscribe = useCallback((listener: () => void) => buffer.subscribe(listener), [buffer]);
  const snapshot = useSyncExternalStore(subscribe, buffer.getSnapshot, buffer.getSnapshot);
  return <TerminalLines text={stripAnsi(snapshot.text)} truncated={snapshot.truncated} />;
}

function TerminalLines({ text, truncated }: { text: string; truncated: boolean }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <pre className="act-terminal__body" data-expanded={expanded}>
        {text || ' '}
      </pre>
      {truncated && (
        <div style={{ padding: '0 10px 6px' }}>
          <button
            type="button"
            className="act-btn act-btn--ghost"
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? 'Show less' : 'Show all'}
          </button>
        </div>
      )}
    </>
  );
}

export function Terminal({
  buffer,
  text,
  title = 'Output',
  exitCode,
  running = false,
}: {
  buffer?: StreamBuffer | undefined;
  text?: string;
  title?: string;
  exitCode?: number;
  running?: boolean;
}) {
  const plain = stripAnsi(text ?? '');
  return (
    <div className="act-terminal">
      <div className="act-code__head">
        <span className="act-row__label">{title}</span>
        {exitCode !== undefined && (
          <span className={`act-exit act-tabular ${exitCode === 0 ? '' : 'act-exit--error'}`}>
            Exit {exitCode}
          </span>
        )}
        <span style={{ marginInlineStart: 'auto', display: 'inline-flex', gap: 4 }}>
          <CopyButton value={plain} label="Copy output" />
        </span>
      </div>
      {buffer ? <BufferBody buffer={buffer} /> : <TerminalLines text={plain} truncated={false} />}
      {running && <span className="act-visually-hidden">Running</span>}
    </div>
  );
}
