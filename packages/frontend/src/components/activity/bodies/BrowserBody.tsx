import { useState } from 'react';
import { useApp } from '../../../AppContext';
import type { ToolStep } from '../model';
import { Icon } from '../icons';
import { Favicon } from '../primitives/Favicon';
import { pageTitleOf, screenshotsOf } from '../toolOutput';
import { getToolDefinition, hostOf, previewForTool } from '../toolRegistry';

export default function BrowserBody({ steps }: { steps: readonly ToolStep[] }) {
  const [zoom, setZoom] = useState<string | null>(null);
  const { setBrowserOpen, setBrowserFullscreen } = useApp();
  const shots = screenshotsOf(steps);
  const title = pageTitleOf(steps) || 'Browser';
  const openStep = [...steps].reverse().find((step) => step.name === 'browser_open');
  const url = previewForTool(openStep?.name ?? '', openStep?.args);
  const domain = url ? hostOf(url) : undefined;

  const openBrowser = () => {
    setBrowserFullscreen(false);
    setBrowserOpen(true);
    window.dispatchEvent(
      new CustomEvent('palimind:browser-active', {
        detail: { tool: 'browser_open', args: { url } },
      }),
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div className="act-passage__head">
        <Favicon domain={domain} title={title} />
        <span className="act-row__label" style={{ color: 'var(--act-text)' }}>
          {title}
        </span>
        {domain && <span className="act-result__domain">{domain}</span>}
        <span className="act-chip act-tabular">{steps.length} steps</span>
        <button
          type="button"
          className="act-chip act-chip--action"
          onClick={openBrowser}
          title="Open the shared browser"
        >
          View
        </button>
      </div>

      <div className="act-tree">
        {steps.map((step) => {
          const definition = getToolDefinition(step.name);
          return (
            <div key={step.id} className="act-tree__row">
              <Icon name={definition.icon} size={13} />
              <span>{definition.done}</span>
              {previewForTool(step.name, step.args) && (
                <span className="act-muted act-mono">
                  {previewForTool(step.name, step.args)}
                </span>
              )}
              {step.status === 'error' && <span className="act-status--error">Failed</span>}
            </div>
          );
        })}
      </div>

      {shots.length > 0 && (
        <div className="act-filmstrip">
          {shots.map((shot, index) => (
            <button
              key={`${shot.src.slice(0, 24)}-${index}`}
              type="button"
              className="act-shot"
              onClick={() => setZoom(shot.src)}
              aria-label={`Screenshot ${index + 1}`}
            >
              <img src={shot.src} alt="" loading="lazy" />
            </button>
          ))}
        </div>
      )}

      {zoom && (
        <button
          type="button"
          className="act-shot"
          style={{ width: '100%', aspectRatio: '16 / 10', position: 'relative' }}
          onClick={() => setZoom(null)}
          aria-label="Close screenshot"
        >
          <img src={zoom} alt="" style={{ objectFit: 'contain' }} />
        </button>
      )}
    </div>
  );
}
