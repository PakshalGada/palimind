import { useEffect, useRef, useState } from 'react';

/**
 * Lazily loads Mermaid (kept out of the main bundle via dynamic import) and
 * renders a diagram to SVG. Falls back to an error message on invalid syntax.
 */
export default function MermaidPreview({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setError('');
    (async () => {
      try {
        const mermaid = (await import('mermaid')).default;
        const light = document.documentElement.classList.contains('light-mode');
        mermaid.initialize({
          startOnLoad: false,
          theme: light ? 'default' : 'dark',
          securityLevel: 'strict',
          fontFamily: 'var(--font-sans)',
        });
        const id = `mmd-${Math.random().toString(36).slice(2)}`;
        const { svg } = await mermaid.render(id, code);
        if (!cancelled && containerRef.current) containerRef.current.innerHTML = svg;
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (error) {
    return (
      <div className="artifact-error">
        <strong>Diagram error</strong>
        <pre>{error}</pre>
      </div>
    );
  }
  return <div className="artifact-mermaid" ref={containerRef} />;
}
