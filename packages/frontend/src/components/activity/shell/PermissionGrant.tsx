import { useEffect, useRef } from 'react';
import type { ToolStep } from '../model';
import { Icon } from '../icons';
import { DiffView } from '../primitives/DiffView';
import { CodeView } from '../primitives/CodeView';
import { diffFromStep, parseOutput, textOf } from '../toolOutput';
import { previewForTool } from '../toolRegistry';
import {
  destructiveReason,
  grantDecisionForKey,
  maskSecrets,
  plainAction,
  type GrantDecision,
} from '../grant';

export type { GrantDecision };

function argString(args: unknown, keys: string[]): string {
  if (!args || typeof args !== 'object') return '';
  const record = args as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function toolLabel(name: string): string {
  return name.replace(/_/g, ' ');
}

function Domain({ url }: { url: string }) {
  try {
    return <>{new URL(url).host.replace(/^www\./, '')}</>;
  } catch {
    return <>{url}</>;
  }
}

function Payload({ step }: { step: ToolStep }) {
  const name = step.name;

  if (name === 'write_file' || name === 'search_replace') {
    const diff = diffFromStep(step.output, step.args);
    return (
      <div className="act-grant__reach">
        {diff.before || diff.after ? (
          <DiffView before={diff.before ?? ''} after={diff.after ?? ''} path={diff.path} />
        ) : (
          <span className="act-grant__reach-item act-mono">{previewForTool(name, step.args)}</span>
        )}
      </div>
    );
  }

  if (name === 'run_python' || name === 'run_shell') {
    const code = argString(step.args, ['code', 'source', 'script']);
    const command = argString(step.args, ['command', 'cmd', 'shell']);
    return (
      <div className="act-grant__reach">
        <CodeView
          code={maskSecrets(code || command)}
          language={code ? 'python' : 'bash'}
          title={code ? 'Python' : 'Command'}
          maxLines={30}
          copy={false}
        />
      </div>
    );
  }

  if (name.startsWith('browser_')) {
    const label = argString(step.args, ['label', 'element', 'selector', 'name', 'ref']);
    const url = argString(step.args, ['url', 'domain', 'page']);
    const action = name.replace('browser_', '').replace(/_/g, ' ');
    return (
      <div className="act-grant__reach">
        <span className="act-grant__reach-item">
          <span className="act-mono">{action}</span>
          {label && <span>"{maskSecrets(label)}"</span>}
          {url && (
            <span className="act-muted">
              on <Domain url={url} />
            </span>
          )}
        </span>
      </div>
    );
  }

  const output = parseOutput(step.output);
  return (
    <div className="act-grant__reach">
      <span className="act-grant__reach-item act-mono">
        {maskSecrets(previewForTool(name, step.args) || textOf(output).slice(0, 120))}
      </span>
    </div>
  );
}

export function PermissionGrant({
  step,
  allowedForRun,
  restored,
  onResolve,
}: {
  step: ToolStep;
  allowedForRun: boolean;
  /** True when the run was restored from persisted history. */
  restored?: boolean;
  onResolve: (decision: GrantDecision) => void;
}) {
  const primary = useRef<HTMLButtonElement>(null);
  const submitted = useRef(false);
  const pending = step.status === 'awaiting_approval';
  const resolve = (decision: GrantDecision) => {
    // One decision per request: a double click or held key must not send a
    // second (possibly contradicting) approval before the row re-renders.
    if (submitted.current) return;
    submitted.current = true;
    onResolve(decision);
  };
  const action = plainAction(step);
  const safeAction = maskSecrets(action);
  const destructive = destructiveReason(step);
  useEffect(() => {
    if (pending && !restored) primary.current?.focus();
  }, [pending, restored]);

  if (!pending) {
    const label =
      step.status === 'denied'
        ? 'Denied'
        : step.status === 'cancelled'
          ? 'Cancelled'
          : 'Allowed';
    return (
      <div className="act-grant__resolved">
        <Icon name={label === 'Allowed' ? 'check' : 'x'} size={13} />
        <span>{label}</span>
        {label === 'Allowed' && allowedForRun && (
          <span className="act-grant__note">Allowed for this run</span>
        )}
      </div>
    );
  }

  return (
    <div
      className={`act-grant${restored ? '' : ' act-attention'}`}
      role="group"
      aria-label={`Needs approval: ${safeAction}`}
      data-pending-approval={step.id}
      onKeyDown={(event) => {
        const target = event.target as HTMLElement;
        const decision = grantDecisionForKey({
          key: event.key,
          targetIsButton: target.closest('button') != null,
        });
        if (decision) {
          event.preventDefault();
          resolve(decision);
        }
      }}
    >
      <span className="act-visually-hidden" aria-live="assertive">
        Approval requested: {safeAction}
      </span>

      <div className="act-grant__head">
        <Icon name="lock" size={15} />
        <span className="act-grant__title">Needs approval</span>
        <code className="act-grant__tool act-mono">{toolLabel(step.name)}</code>
        {restored && <span className="act-grant__note">Requested earlier</span>}
      </div>

      <div className="act-grant__action">{safeAction}</div>

      <Payload step={step} />

      {destructive && (
        <div className="act-grant__warning">
          <Icon name="triangle-alert" size={13} />
          <span>Review carefully</span>
        </div>
      )}

      <div className="act-grant__foot">
        <div className="act-grant__actions">
          <button type="button" className="act-btn act-btn--danger-ghost" onClick={() => resolve('deny')}>
            Deny
          </button>
          <span className="act-grant__scope">
            <button type="button" className="act-btn act-btn--ghost" onClick={() => resolve('run')}>
              Allow for this run
            </button>
            <span className="act-grant__scope-note">Per tool name · this run only</span>
          </span>
          <button
            type="button"
            ref={primary}
            className="act-btn act-btn--primary"
            onClick={() => resolve('once')}
          >
            Allow once
          </button>
        </div>
        <p className="act-grant__hint">Enter allow once · A allow for this run · Esc deny</p>
      </div>
    </div>
  );
}
