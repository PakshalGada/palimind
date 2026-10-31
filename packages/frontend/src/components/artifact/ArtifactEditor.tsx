import { useEffect, useMemo, useRef, useState } from 'react';
import { highlightCode } from '../../utils/highlight';

/** Above this size the highlight overlay is skipped to keep typing cheap. */
const MAX_HIGHLIGHT_CHARS = 80_000;
const IDLE_MS = 260;

function countLines(value: string): number {
  let lines = 1;
  for (let i = 0; i < value.length; i++) {
    if (value.charCodeAt(i) === 10) lines += 1;
  }
  return lines;
}

function leadingWhitespace(value: string, position: number): string {
  const lineStart = value.lastIndexOf('\n', position - 1) + 1;
  return /^[ \t]*/.exec(value.slice(lineStart, position))?.[0] ?? '';
}

/**
 * A lightweight code editor: a textarea over a syntax-highlighted mirror.
 *
 * Highlighting the whole document on every keystroke is what made the old
 * editor lag on large artifacts. While the user is typing we show plain
 * text; the highlighted mirror is built once, after a short idle period.
 */
export default function ArtifactEditor({
  value,
  language,
  onChange,
}: {
  value: string;
  language: string;
  onChange: (value: string) => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const highlightRef = useRef<HTMLPreElement>(null);
  const gutterRef = useRef<HTMLDivElement>(null);
  const scrollFrame = useRef<number | null>(null);
  const idleTimer = useRef<number | null>(null);

  const [typing, setTyping] = useState(false);
  const [highlight, setHighlight] = useState<{ text: string; html: string } | null>(null);
  const [cursor, setCursor] = useState({ line: 1, column: 1 });

  const lang = (language || 'text').toLowerCase();
  const plainLanguage = lang === 'text' || lang === 'plaintext' || lang === 'plain';
  const overLimit = value.length > MAX_HIGHLIGHT_CHARS;
  const lineCount = useMemo(() => countLines(value), [value]);
  const lineNumbers = useMemo(
    () => Array.from({ length: Math.max(lineCount, 1) }, (_, index) => index + 1).join('\n'),
    [lineCount],
  );

  // Re-highlight only after the user stops typing, and never for huge files.
  useEffect(() => {
    if (typing || overLimit || plainLanguage) {
      if (plainLanguage || overLimit) setHighlight(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      const html = highlightCode(value, lang, { autoDetect: false }).html;
      if (!cancelled) setHighlight({ text: value, html });
    }, 32);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [value, lang, typing, overLimit, plainLanguage]);

  useEffect(
    () => () => {
      if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
      if (idleTimer.current !== null) window.clearTimeout(idleTimer.current);
    },
    [],
  );

  const showHighlight = !typing && !overLimit && !plainLanguage && highlight?.text === value;

  const markTyping = () => {
    setTyping(true);
    if (idleTimer.current !== null) window.clearTimeout(idleTimer.current);
    idleTimer.current = window.setTimeout(() => setTyping(false), IDLE_MS);
  };

  const syncScroll = () => {
    if (scrollFrame.current !== null) return;
    scrollFrame.current = requestAnimationFrame(() => {
      scrollFrame.current = null;
      const textarea = textareaRef.current;
      if (!textarea) return;
      if (highlightRef.current) {
        highlightRef.current.scrollTop = textarea.scrollTop;
        highlightRef.current.scrollLeft = textarea.scrollLeft;
      }
      if (gutterRef.current) gutterRef.current.scrollTop = textarea.scrollTop;
    });
  };

  const updateCursor = (element?: HTMLTextAreaElement) => {
    const textarea = element ?? textareaRef.current;
    if (!textarea) return;
    const upToCursor = textarea.value.slice(0, textarea.selectionStart ?? 0);
    const lines = upToCursor.split('\n');
    const next = {
      line: lines.length,
      column: (lines[lines.length - 1]?.length ?? 0) + 1,
    };
    setCursor(current =>
      current.line === next.line && current.column === next.column ? current : next,
    );
  };

  const edit = (next: string, selection?: { start: number; end: number }) => {
    markTyping();
    onChange(next);
    if (selection) {
      window.requestAnimationFrame(() => {
        const textarea = textareaRef.current;
        if (!textarea) return;
        textarea.selectionStart = selection.start;
        textarea.selectionEnd = selection.end;
        updateCursor(textarea);
      });
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.nativeEvent.isComposing) return;
    const textarea = event.currentTarget;
    if (event.key === 'Tab') {
      event.preventDefault();
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      if (start === end) {
        edit(`${value.slice(0, start)}  ${value.slice(end)}`, {
          start: start + 2,
          end: start + 2,
        });
      } else {
        // Indent every line touched by the selection.
        const before = value.slice(0, start);
        const range = value.slice(start, end);
        const after = value.slice(end);
        const indented = range.replace(/^/gm, '  ');
        const added = indented.length - range.length;
        edit(`${before}${indented}${after}`, { start, end: end + added });
      }
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      const start = textarea.selectionStart;
      const indent = leadingWhitespace(value, start);
      if (!indent) return;
      event.preventDefault();
      edit(`${value.slice(0, start)}\n${indent}${value.slice(textarea.selectionEnd)}`, {
        start: start + 1 + indent.length,
        end: start + 1 + indent.length,
      });
    }
  };

  return (
    <div className={`artp-editor${showHighlight ? '' : ' is-plain'}`}>
      <div className="artp-editor-wrap">
        <div className="artp-editor-gutter" ref={gutterRef} aria-hidden="true">
          <pre className="artp-editor-lines">{lineNumbers}</pre>
        </div>
        <div className="artp-editor-stage">
          <pre className="artp-editor-mirror hljs" ref={highlightRef} aria-hidden="true">
            <code dangerouslySetInnerHTML={{ __html: `${highlight?.html ?? ''}\n` }} />
          </pre>
          <textarea
            ref={textareaRef}
            className="artp-editor-input"
            value={value}
            wrap="off"
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            aria-label="Artifact editor"
            autoFocus
            onChange={event => edit(event.target.value)}
            onScroll={syncScroll}
            onSelect={() => updateCursor()}
            onClick={() => updateCursor()}
            onKeyUp={() => updateCursor()}
            onKeyDown={handleKeyDown}
          />
        </div>
      </div>
      <div className="artp-editor-status">
        <span className="artp-editor-status-cell">
          Ln {cursor.line}, Col {cursor.column}
        </span>
        <span className="artp-editor-status-cell">
          {lineCount.toLocaleString()} lines · {value.length.toLocaleString()} chars
        </span>
        <span className="artp-editor-status-cell artp-editor-status-lang">
          {overLimit ? 'plain text (large file)' : language ? language.toUpperCase() : 'TEXT'}
        </span>
      </div>
    </div>
  );
}
