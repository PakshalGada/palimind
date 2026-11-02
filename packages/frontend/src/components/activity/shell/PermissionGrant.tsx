import { useEffect, useRef } from 'react';
import type { ToolStep } from '../model';
import { Icon } from '../icons';
import { DiffView } from '../primitives/DiffView';
import { CodeView } from '../primitives/CodeView';
import { diffFromStep, parseOutput, textOf } from '../toolOutput';
import { previewForTool } from '../toolRegistry';

export type GrantDecision = 'once' | 'run' | 'deny';

const DESTRUCTIVE = [
  /\brm\s+-[a-z]*[rf]/i,
  /\bsudo\b/i,
  /\bmkfs\b/i,
  /\bdd\s+if=/i,
  /curl[^|]*\|\s*(sh|bash|zsh)/i,
  /wget[^|]*\|\s*(sh|bash|zsh)/i,
  />\s*\/(etc|usr|bin|var)\//i,
];

function argString(args: unknown, keys: string[]): string {
  if (!args || typeof args !== 'object') return '';
  const record = args as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function isDestructive(command: string): boolean {
  return DESTRUCTIVE.some((pattern) => pattern.test(command));
}

function Reach({ step }: { step: ToolStep }) {
  const name = step.name;
  if (name === 'write_file' || name === 'search_replace') {
    const diff = diffFromStep(step.output, step.args);
    return (
      <div className="act-grant__reach">
        <span className="act-row__label act-mono">{diff.path}</span>
        {diff.before || diff.after ? (
          <DiffView before={diff.before ?? ''} after={diff.after ?? ''} path={diff.path} />
        ) : (
          <span className="act-muted act-mono">{previewForTool(name, step.args)}</span>
        )}
      </div>
    );
  }

  if (name === 'run_python' || name === 'run_shell') {
    const code = argString(step.args, ['code', 'source', 'script']);
    const command = argString(step.args, ['command', 'cmd', 'shell']);
    const destructive = command ? isDestructive(command) : false;
    return (
      <div className="act-grant__reach">
        <CodeView
          code={code || command}
          language={code ? 'python' : 'bash'}
          title={code ? 'Python' : 'Command'}
          maxLines={30}
          copy={false}
        />
        {destructive && (
          <span className="act-grant__warning">
            <Icon name="triangle-alert" size={13} />
            Review carefully
          </span>
        )}
      </div>
    );
  }

  if (name.startsWith('browser_')) {
    const label = previewForTool(name, step.args);
    const action = name.replace('browser_', '');
    return (
      <div className="act-grant__reach">
        <span className="act-grant__reach-item">{action}</span>
        {label && <span className="act-grant__reach-item act-mono">{label}</span>}
      </div>
    );
  }

  const output = parseOutput(step.output);
  return (
    <div className="act-grant__reach">
      <span className="act-grant__reach-item act-mono">
        {previewForTool(name, step.args) || textOf(output).slice(0, 80)}
      </span>
    </div>
  );
}

export function PermissionGrant({
  step,
  allowedForRun,
  onResolve,
}: {
  step: ToolStep;
  allowedForRun: boolean;
  onResolve: (decision: GrantDecision) => void;
}) {
  const primary = useRef<HTMLButtonElement>(null);
  const pending = step.status === 'awaiting_approval';

  useEffect(() => {
    if (pending) primary.current?.focus();
  }, [pending]);

  if (!pending) {
    const label =
      step.status === 'denied'
        ? 'Denied'
        : step.status === 'cancelled'
          ? 'Cancelled'
          : 'Allowed';
    return (
      <div className="act-grant__resolved">
        <Icon name={label === 'Denied' || label === 'Cancelled' ? 'x' : 'check'} size={13} />
        {label}
      </div>
    );
  }

  return (
    <div
      className="act-grant act-attention"
      role="group"
      aria-label="Tool approval required"
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          onResolve('deny');
        } else if (event.key === 'Enter' && event.target === event.currentTarget) {
          event.preventDefault();
          onResolve('once');
        }
      }}
    >
      <div className="act-grant__head">
        <Icon name="lock" size={14} />
        <span className="act-grant__title">Needs approval</span>
        {allowedForRun && <span className="act-grant__note">Allowed for this run</span>}
      </div>
      <Reach step={step} />
      <div className="act-grant__actions">
        <button type="button" className="act-btn" onClick={() => onResolve('deny')}>
          Deny
        </button>
        <button type="button" className="act-btn" onClick={() => onResolve('run')}>
          Allow for this run
        </button>
        <button
          type="button"
          ref={primary}
          className="act-btn act-btn--primary"
          onClick={() => onResolve('once')}
        >
          Allow once
        </button>
      </div>
    </div>
  );
}
