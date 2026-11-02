import { lazy, Suspense, useMemo, useState } from 'react';
import type { ToolStep } from '../model';
import { formatToolDuration } from '../model';
import { useNow } from '../hooks';
import { Icon } from '../icons';
import { Disclosure } from '../primitives/Disclosure';
import { Rail, RailItem } from '../primitives/Rail';
import type { ActivityStore } from '../store';
import { getToolDefinition, hostOf, previewForTool } from '../toolRegistry';
import { pageTitleOf } from '../toolOutput';
import { timelineOverlaps, unitsOf, type TimelineUnit } from '../grouping';
import { ToolRow } from './ToolRow';
import type { GrantDecision } from './PermissionGrant';

const BrowserBody = lazy(() => import('../bodies/BrowserBody'));

interface TimelineProps {
  steps: readonly ToolStep[];
  store: ActivityStore;
  view?: 'rail' | 'gantt';
  depth?: number;
  compact?: boolean;
  onRetry?: (step: ToolStep) => void;
  onResolveApproval?: (step: ToolStep, decision: GrantDecision) => void;
}

function Gantt({ steps, running }: { steps: readonly ToolStep[]; running: boolean }) {
  const now = useNow(running);
  const starts = steps.map((step) => step.startedAt).filter((value): value is number => value != null);
  const runStart = starts.length ? Math.min(...starts) : now;
  const runEnd = Math.max(
    now,
    ...steps.map((step) => step.endedAt ?? (step.startedAt ?? runStart) + (step.durationMs ?? 0)),
  );
  const total = Math.max(1, runEnd - runStart);

  return (
    <div className="act-gantt">
      {steps.map((step) => {
        const definition = getToolDefinition(step.name);
        const start = step.startedAt ?? runStart;
        const end = step.endedAt ?? (step.status === 'running' ? now : start + (step.durationMs ?? 0));
        const offset = ((start - runStart) / total) * 100;
        const width = Math.max(1.5, ((end - start) / total) * 100);
        const error = step.status === 'error';
        const isRunning = step.status === 'running';
        return (
          <div key={step.id} className="act-gantt__row">
            <span className="act-gantt__label">
              <Icon name={definition.icon} size={13} />
              <span>{definition.done}</span>
            </span>
            <span className="act-gantt__track">
              <span
                className={`act-gantt__bar ${isRunning ? 'act-gantt__bar--running' : ''} ${
                  error ? 'act-gantt__bar--error' : ''
                }`.trim()}
                style={{ marginInlineStart: `${offset}%`, width: `${width}%` }}
              />
            </span>
            <span className="act-muted act-tabular">
              {step.durationMs != null ? formatToolDuration(step.durationMs) : isRunning ? 'Running' : ''}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function BrowserUnit({ unit }: { unit: TimelineUnit }) {
  const [open, setOpen] = useState(false);
  const group = unit.steps;
  const titleStep = [...group].reverse().find((step) => step.name === 'browser_open');
  const url = titleStep ? previewForTool(titleStep.name, titleStep.args) : '';
  const domain = url ? hostOf(url) : '';
  const pageTitle = pageTitleOf(group);
  const running = group.some((step) => step.status === 'running');
  return (
    <RailItem status={running ? 'running' : 'success'}>
      <Disclosure
        open={open}
        onOpenChange={setOpen}
        summaryClassName="act-row__head"
        contentClassName="act-row__body"
        summary={
          <>
            <Icon
              name={running ? 'loader-2' : 'app-window'}
              size={14}
              className={running ? 'act-spin' : ''}
            />
            <span className="act-row__label">{running ? 'Browsing' : 'Browser'}</span>
            {(pageTitle || domain) && <span className="act-row__preview">{pageTitle || domain}</span>}
            <span className="act-row__trail">
              <span className="act-chip act-tabular">{group.length} steps</span>
            </span>
          </>
        }
      >
        <Suspense fallback={<div className="act-empty">Loading</div>}>
          <BrowserBody steps={group} />
        </Suspense>
      </Disclosure>
    </RailItem>
  );
}

function ParallelUnit({
  unit,
  store,
  depth,
  compact,
  onRetry,
  onResolveApproval,
}: {
  unit: TimelineUnit;
  store: ActivityStore;
  depth: number;
  compact?: boolean;
  onRetry?: (step: ToolStep) => void;
  onResolveApproval?: (step: ToolStep, decision: GrantDecision) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <RailItem status="success">
      <Disclosure
        open={open}
        onOpenChange={setOpen}
        summaryClassName="act-row__head"
        contentClassName="act-row__body"
        summary={
          <>
            <Icon name="layers" size={14} />
            <span className="act-row__label">Ran {unit.steps.length} tools</span>
          </>
        }
      >
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {unit.steps.map((step) => (
            <ToolRow
              key={step.id}
              id={step.id}
              store={store}
              shimmer={false}
              depth={depth + 1}
              compact={compact}
              onRetry={onRetry}
              onResolveApproval={onResolveApproval}
            />
          ))}
        </div>
      </Disclosure>
    </RailItem>
  );
}

export function RunTimeline({
  steps,
  store,
  view = 'rail',
  depth = 0,
  compact = false,
  onRetry,
  onResolveApproval,
}: TimelineProps) {
  const units = useMemo(() => unitsOf(steps), [steps]);
  const runningIds = useMemo(() => {
    let count = 0;
    return new Set(
      steps
        .filter((step) => step.status === 'running')
        .filter(() => (count += 1) <= 3)
        .map((step) => step.id),
    );
  }, [steps]);

  if (steps.length === 0) return null;
  if (view === 'gantt' && (steps.length >= 3 || timelineOverlaps(steps))) {
    return <Gantt steps={steps} running={steps.some((step) => step.status === 'running')} />;
  }

  return (
    <Rail>
      {units.map((unit) => {
        if (unit.kind === 'browser') return <BrowserUnit key={unit.key} unit={unit} />;
        if (unit.kind === 'parallel') {
          return (
            <ParallelUnit
              key={unit.key}
              unit={unit}
              store={store}
              depth={depth}
              compact={compact}
              onRetry={onRetry}
              onResolveApproval={onResolveApproval}
            />
          );
        }
        const step = unit.steps[0];
        return (
          <RailItem key={step.id} status={step.status}>
            <ToolRow
              id={step.id}
              store={store}
              shimmer={runningIds.has(step.id)}
              depth={depth}
              compact={compact}
              onRetry={onRetry}
              onResolveApproval={onResolveApproval}
            />
          </RailItem>
        );
      })}
    </Rail>
  );
}
