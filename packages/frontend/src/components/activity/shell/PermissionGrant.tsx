import { useEffect, useRef, useState } from 'react';
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
  onResolve: (decision: GrantDecision, args?: Record<string, unknown>) => void;
}) {
  const primary = useRef<HTMLButtonElement>(null);
  const submitted = useRef(false);
  const pending = step.status === 'awaiting_approval';
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [editError, setEditError] = useState('');
  const canEdit = Boolean(step.args && typeof step.args === 'object' && !Array.isArray(step.args));

  useEffect(() => {
    setEditing(false);
    setDraft('');
    setEditError('');
  }, [step.id]);

  const parseDraft = (): { value?: Record<string, unknown>; error?: string } => {
    try {
      const parsed = JSON.parse(draft);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return { error: 'Arguments must be a JSON object.' };
      }
      return { value: parsed as Record<string, unknown> };
    } catch {
      return { error: 'Arguments must be valid JSON.' };
    }
  };

  const resolve = (decision: GrantDecision, args?: Record<string, unknown>) => {
    // One decision per request: a double click or held key must not send a
    // second (possibly contradicting) approval before the row re-renders.
    if (submitted.current) return;
    submitted.current = true;
    onResolve(decision, args);
  };

  const allow = (decision: 'once' | 'run') => {
    if (!editing) {
      resolve(decision);
      return;
    }
    const parsed = parseDraft();
    if (parsed.error) {
      setEditError(parsed.error);
      return;
    }
    resolve(decision, parsed.value);
  };

  const startEdit = () => {
    setDraft(JSON.stringify(step.args ?? {}, null, 2));
    setEditError('');
    setEditing(true);
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
        if (target.closest('textarea, input, select')) return;
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

      {editing && (
        <div className="act-grant__editor">
          <label>
            Edit arguments (JSON)
            <textarea
              value={draft}
              spellCheck={false}
              rows={Math.min(12, Math.max(4, draft.split('\n').length))}
              onChange={(event) => {
                setDraft(event.target.value);
                if (editError) setEditError('');
              }}
            />
          </label>
          {editError && <span className="act-grant__error">{editError}</span>}
          <div className="act-grant__editor-actions">
            <button
              type="button"
              className="act-btn act-btn--ghost"
              onClick={() => {
                setEditing(false);
                setEditError('');
              }}
            >
              Cancel edit
            </button>
            <button type="button" className="act-btn act-btn--primary" onClick={() => allow('once')}>
              Allow edited
            </button>
          </div>
        </div>
      )}

      <div className="act-grant__foot">
        <div className="act-grant__actions">
          <button type="button" className="act-btn act-btn--danger-ghost" onClick={() => resolve('deny')}>
            Deny
          </button>
          {canEdit && !editing && (
            <button type="button" className="act-btn act-btn--ghost" onClick={startEdit}>
              Edit args
            </button>
          )}
          <span className="act-grant__scope">
            <button type="button" className="act-btn act-btn--ghost" onClick={() => allow('run')}>
              Allow for this run
            </button>
            <span className="act-grant__scope-note">Per tool name · this run only</span>
          </span>
          <button
            type="button"
            ref={primary}
            className="act-btn act-btn--primary"
            onClick={() => allow('once')}
          >
            Allow once
          </button>
        </div>
        <p className="act-grant__hint">
          {editing
            ? 'Edit the JSON, then allow the corrected call.'
            : 'Enter allow once · A allow for this run · Esc deny'}
        </p>
      </div>
    </div>
  );
}
