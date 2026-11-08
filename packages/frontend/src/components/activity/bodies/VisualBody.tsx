import { ExternalLink } from 'lucide-react';
import type { ToolStep } from '../model';
import { visualOf } from '../toolOutput';

/**
 * A sandboxed HTML reply published by `html_render`. The backend serves the
 * page with a sandbox CSP; the iframe repeats the restrictions for browsers
 * that ignore the header.
 */
export default function VisualBody({ step }: { step: ToolStep }) {
  const visual = visualOf(step.output);
  if (!visual) {
    return <div className="act-empty">This visual could not be loaded.</div>;
  }
  const height = Math.max(160, Math.min(visual.height || 600, 1600));
  return (
    <div className="act-visual">
      <div className="act-visual__head">
        <span className="act-section-title">{visual.title}</span>
        <a
          className="act-chip act-chip--action"
          href={visual.url}
          target="_blank"
          rel="noreferrer noopener"
        >
          <ExternalLink size={11} /> Open
        </a>
      </div>
      <iframe
        className="act-visual__frame"
        title={visual.title}
        src={visual.url}
        sandbox="allow-scripts allow-forms allow-modals allow-popups"
        style={{ height }}
        loading="lazy"
      />
    </div>
  );
}
