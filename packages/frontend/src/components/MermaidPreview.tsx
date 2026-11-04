import { useEffect, useRef, useState } from 'react';
import { renderMermaid } from '../utils/artifactMermaid';

/**
 * Lazily loads Mermaid (kept out of the main bundle via dynamic import) and
 * renders a diagram to SVG. Rendering is debounced so typing in the artifact
 * editor does not re-run Mermaid on every keystroke.
 */
export default function MermaidPreview({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      (async () => {
        try {
          const id = `mmd-${Math.random().toString(36).slice(2)}`;
          const svg = await renderMermaid(id, code);
          if (cancelled) return;
          setError('');
          if (containerRef.current) containerRef.current.innerHTML = svg;
        } catch (e) {
          if (!cancelled) setError(e instanceof Error ? e.message : String(e));
        }
      })();
    }, 350);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [code]);

  return (
    <>
      {error && (
        <div className="artifact-error">
          <strong>Diagram error</strong>
          <pre>{error}</pre>
        </div>
      )}
      <div
        className="artifact-mermaid"
        ref={containerRef}
        style={error ? { display: 'none' } : undefined}
      />
    </>
  );
}
