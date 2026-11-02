import type { ToolStep } from '../model';
import type { ActivityState } from '../model';
import type { ActivityStore } from '../store';
import { Icon } from '../icons';
import { RunTimeline } from '../shell/RunTimeline';

const MAX_DEPTH = 3;

export default function SubagentBody({
  step,
  state,
  store,
  depth = 0,
}: {
  step: ToolStep;
  state: ActivityState;
  store: ActivityStore;
  depth?: number;
}) {
  const children = state.steps.filter((entry) => entry.parentId === step.id);
  if (children.length === 0) {
    const output = step.output;
    const text =
      typeof output === 'string'
        ? output
        : output && typeof output === 'object'
          ? String((output as Record<string, unknown>).output ?? '')
          : '';
    return <div className="act-empty">{text || 'No child steps'}</div>;
  }
  if (depth >= MAX_DEPTH) {
    return (
      <div className="act-muted" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Icon name="git-fork" size={12} />
        {children.length} deeper steps
      </div>
    );
  }
  return (
    <div className="act-subagent">
      <div className="act-section-title">
        <Icon name="git-fork" size={12} />
        <span>Sub-agent</span>
        <span className="act-tabular">{children.length} steps</span>
      </div>
      <RunTimeline
        steps={children}
        store={store}
        depth={depth + 1}
        compact
      />
    </div>
  );
}
