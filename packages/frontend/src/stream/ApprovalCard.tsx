import { useState } from 'react';
import { useActivity } from '../AppContext';
import { api } from '../api';
import type { ApprovalPrompt } from './types';

function formatArgs(args: unknown): string {
  if (typeof args === 'string') return args;
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}

/**
 * Inline human-approval prompt for agent tool calls. Previously ~60 lines of
 * createElement/inline CSS inside the SSE handler.
 */
export default function ApprovalCard({ prompt }: { prompt: ApprovalPrompt }) {
  const { setThinkingText } = useActivity();
  const [correction, setCorrection] = useState('');
  const [status, setStatus] = useState<'pending' | 'approved' | 'rejected'>('pending');

  const resolved = status !== 'pending';

  const finish = (approved: boolean) => {
    if (resolved) return;
    setStatus(approved ? 'approved' : 'rejected');
    api.agents.approve(prompt.agentId, approved, correction).catch(() => {});
    setThinkingText(approved ? 'Resuming…' : 'Rejected');
  };

  return (
    <div className="approval-card" role="group" aria-label="Tool approval required">
      <div className="approval-card__title">
        <strong>Approval required</strong> — <code>{prompt.tool}</code>
      </div>

      {prompt.args != null && (
        <pre className="approval-card__args">{formatArgs(prompt.args)}</pre>
      )}

      <input
        type="text"
        className="approval-card__input"
        placeholder="Optional correction / feedback…"
        value={correction}
        disabled={resolved}
        onChange={(e) => setCorrection(e.target.value)}
      />

      <div className="approval-card__actions">
        <button
          type="button"
          className="action-btn primary"
          disabled={resolved}
          onClick={() => finish(true)}
        >
          Approve
        </button>
        <button
          type="button"
          className="action-btn danger-btn"
          disabled={resolved}
          onClick={() => finish(false)}
        >
          Reject
        </button>
      </div>

      {resolved && (
        <div className="approval-card__status">
          {status === 'approved' ? 'Approved — resuming…' : 'Rejected.'}
        </div>
      )}
    </div>
  );
}
