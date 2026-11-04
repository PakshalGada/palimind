import { memo, useState } from 'react';
import type { ToolStep } from '../model';
import { formatToolDuration } from '../model';
import { useStep } from '../hooks';
import { Icon } from '../icons';
import { maskSecrets } from '../grant';
import { Disclosure } from '../primitives/Disclosure';
import { CopyButton } from '../primitives/CopyButton';
import { ShimmerText } from '../primitives/ShimmerText';
import { SourceStack } from '../primitives/SourceStack';
import { StatusIcon } from '../primitives/StatusIcon';
import type { ActivityStore } from '../store';
import { normalizePassages, normalizeResults, textOf } from '../toolOutput';
import { getToolDefinition, previewForTool, toolDisplayName } from '../toolRegistry';
import { ToolBody } from '../bodies/ToolBody';
import { PermissionGrant, type GrantDecision } from './PermissionGrant';

function inputText(args: unknown): string {
  if (args == null) return '';
  if (typeof args === 'string') return args;
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}

function settledDuration(step: ToolStep): string {
  if (step.durationMs != null) return formatToolDuration(step.durationMs);
  return '';
}

export interface ToolRowProps {
  id: string;
  store: ActivityStore;
  shimmer: boolean;
  depth?: number;
  compact?: boolean;
  browserSteps?: readonly ToolStep[];
  onRetry?: (step: ToolStep) => void;
  onResolveApproval?: (step: ToolStep, decision: GrantDecision) => void;
}

export const ToolRow = memo(function ToolRow({
  id,
  store,
  shimmer,
  depth = 0,
  compact = false,
  browserSteps,
  onRetry,
  onResolveApproval,
}: ToolRowProps) {
  const step = useStep(store, id);
  const [manual, setManual] = useState<boolean | null>(null);

  if (!step) return null;
  const definition = getToolDefinition(step.name);
  const generic = definition.family === 'generic';
  const runningLabel = generic ? `Using ${toolDisplayName(step.name)}` : definition.running;
  const doneLabel = generic ? `Used ${toolDisplayName(step.name)}` : definition.done;
  const running = step.status === 'running' || step.status === 'queued';
  const autoOpen =
    step.status === 'awaiting_approval' ||
    (definition.family === 'code-run' && step.status === 'running');
  const open = manual ?? autoOpen;
  const preview = previewForTool(step.name, step.args);
  const visiblePreview = definition.approval ? maskSecrets(preview) : preview;
  const results =
    definition.family === 'search' && step.output != null ? normalizeResults(step.output) : [];
  const passages =
    definition.family === 'passages' && step.output != null ? normalizePassages(step.output) : [];
  const duration = settledDuration(step);

  return (
    <div
      className={`act-row ${step.status === 'error' ? 'act-row--error' : ''} ${
        compact ? 'act-row--compact' : ''
      } ${step.status === 'queued' ? 'act-row--queued' : ''}`.trim()}
      style={depth > 0 ? { marginInlineStart: depth * 10 } : undefined}
    >
      <Disclosure
        open={open}
        onOpenChange={(next) => setManual(next)}
        chevron={false}
        summaryClassName="act-row__head"
        contentClassName="act-row__body"
        summary={
          <>
            <StatusIcon status={step.status} animate={step.status !== 'running' || shimmer} />
            <span className="act-row__toolicon">
              <Icon name={definition.icon} size={14} />
            </span>
            <span className="act-row__label">
              {running && shimmer ? (
                <ShimmerText>{runningLabel}</ShimmerText>
              ) : (
                <span className={running ? '' : 'act-muted'}>{running ? runningLabel : doneLabel}</span>
              )}
            </span>
            {visiblePreview && (
              <span className="act-row__preview" title={visiblePreview}>
                {visiblePreview}
              </span>
            )}
            <span className="act-row__trail">
              {results.length > 0 && (
                <>
                  <SourceStack items={results} />
                  <span className="act-tabular">{results.length} results</span>
                </>
              )}
              {passages.length > 0 && (
                <span className="act-tabular">
                  {passages.length} passages in {new Set(passages.map((item) => item.docName)).size} files
                </span>
              )}
              {duration && step.status !== 'running' && (
                <span className="act-chip act-tabular">{duration}</span>
              )}
              <span className="act-chevron" data-open={open} aria-hidden="true">
                <Icon name="chevron-right" size={14} />
              </span>
            </span>
          </>
        }
      >
        {step.status === 'error' && (
          <div className="act-row__error">
            <span>{step.error ?? 'Tool failed'}</span>
            {onRetry && (
              <button type="button" className="act-btn act-btn--ghost" onClick={() => onRetry(step)}>
                Retry
              </button>
            )}
          </div>
        )}
        {step.status === 'awaiting_approval' && onResolveApproval && (
          <PermissionGrant
            step={step}
            allowedForRun={store.isAllowedForRun(step.name)}
            restored={store.restored}
            onResolve={(decision) => onResolveApproval(step, decision)}
          />
        )}
        {step.status === 'success' && !step.approval && store.isAllowedForRun(step.name) && (
          <div className="act-grant__resolved act-grant__resolved--soft">
            <Icon name="check" size={13} /> Allowed for this run
          </div>
        )}
        {(step.status === 'denied' || step.status === 'cancelled') && (
          <div className="act-row__error" style={{ color: 'var(--act-muted)' }}>
            {step.status === 'denied' ? 'Denied' : 'Cancelled'}
          </div>
        )}
        {step.approval &&
          step.status !== 'awaiting_approval' &&
          step.status !== 'denied' &&
          step.status !== 'cancelled' && (
            <div className="act-grant__resolved">
              <Icon name="check" size={13} /> Allowed
            </div>
          )}
        {step.args != null && (
          <details className="act-row__input">
            <summary>Input</summary>
            <pre>{definition.approval ? maskSecrets(inputText(step.args)) : inputText(step.args)}</pre>
          </details>
        )}
        {step.output != null && (
          <div className="act-section-title">
            <span>Output</span>
            <CopyButton value={textOf(step.output)} />
          </div>
        )}
        <ToolBody step={step} store={store} depth={depth} browserSteps={browserSteps} />
      </Disclosure>
    </div>
  );
});
