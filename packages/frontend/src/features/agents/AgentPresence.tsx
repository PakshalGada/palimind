import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import AgentAvatar from '../../components/AgentAvatar';
import type { ActivityStore } from '../../components/activity/store';
import { botStateForRun } from '../../bots/config';
import type { AgentListItem } from '../../types';

const TOOL_LABELS: { match: string[]; label: string }[] = [
  { match: ['search', 'web', 'arxiv', 'news', 'x_search'], label: 'Searching the web' },
  { match: ['fetch', 'url', 'page', 'browser'], label: 'Reading a page' },
  { match: ['write', 'edit', 'patch', 'replace', 'create'], label: 'Writing a file' },
  { match: ['read', 'list', 'grep', 'tree', 'find'], label: 'Reading files' },
  { match: ['shell', 'python', 'code', 'run', 'bash'], label: 'Running a command' },
  { match: ['memory', 'remember', 'recall'], label: 'Checking memory' },
  { match: ['ask', 'question', 'message', 'agent'], label: 'Talking to a teammate' },
];

function labelForTool(tool: string): string {
  const name = tool.toLowerCase();
  for (const entry of TOOL_LABELS) {
    if (entry.match.some((token) => name.includes(token))) return entry.label;
  }
  return 'Working';
}

function elapsed(startedAt: number | null, now = Date.now()): string {
  if (!startedAt) return '';
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export default function AgentPresence({
  agent,
  streaming,
  store,
  startedAt,
  activityLabel,
}: {
  agent: AgentListItem;
  streaming: boolean;
  store: ActivityStore;
  startedAt: number | null;
  activityLabel?: string | null;
}) {
  const activity = useSyncExternalStore(store.subscribe, store.getState, store.getState);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!streaming) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [streaming]);

  const running = useMemo(() => {
    if (!activity) return null;
    for (let i = activity.steps.length - 1; i >= 0; i -= 1) {
      if (activity.steps[i].status === 'running') return activity.steps[i];
    }
    return activity.steps[activity.steps.length - 1] || null;
  }, [activity]);

  const status = activity?.status ?? 'idle';
  const state = botStateForRun({ status });

  if (!streaming) {
    const last = agent.last_run_at
      ? new Date(agent.last_run_at * 1000).toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        })
      : '';
    return (
      <div className="ag-presence ag-presence--idle" aria-live="polite">
        <AgentAvatar
          config={agent.avatar_config}
          type={agent.avatar_type === 'upload' ? 'upload' : 'bot'}
          upload={agent.avatar_upload}
          state="default"
          size={18}
        />
        <span>{agent.running ? 'Working in the background' : last ? `Last active ${last}` : 'Ready'}</span>
      </div>
    );
  }

  const label =
    activityLabel ||
    (running ? labelForTool(running.name) : status === 'awaiting_input' ? 'Waiting for you' : 'Thinking');

  return (
    <div className="ag-presence" role="status" aria-live="polite">
      <AgentAvatar
        config={agent.avatar_config}
        type={agent.avatar_type === 'upload' ? 'upload' : 'bot'}
        upload={agent.avatar_upload}
        state={state}
        size={22}
      />
      <span className="ag-presence__name">{agent.display_name || agent.name}</span>
      <span className="ag-presence__dots" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span className="ag-presence__label">{label}</span>
      {startedAt ? <span className="ag-presence__time">{elapsed(startedAt, now)}</span> : null}
    </div>
  );
}
