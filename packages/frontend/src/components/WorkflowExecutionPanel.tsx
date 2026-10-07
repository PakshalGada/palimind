import { X, CheckCircle2, XCircle, Clock, AlertTriangle } from 'lucide-react';
import type { WorkflowExecution, Workflow } from '../types';

interface WorkflowExecutionPanelProps {
  execution: WorkflowExecution;
  workflow: Workflow;
  onClose: () => void;
}

export default function WorkflowExecutionPanel({ execution, workflow, onClose }: WorkflowExecutionPanelProps) {
  const statusIcon =
    execution.status === 'completed' ? (
      <CheckCircle2 size={15} />
    ) : execution.status === 'failed' ? (
      <XCircle size={15} />
    ) : execution.status === 'running' ? (
      <Clock size={15} />
    ) : (
      <AlertTriangle size={15} />
    );

  const statusText =
    execution.status === 'completed'
      ? 'Completed'
      : execution.status === 'failed'
        ? 'Failed'
        : execution.status === 'running'
          ? 'Running'
          : 'Idle';

  const duration = execution.completed_at
    ? execution.completed_at - execution.started_at
    : Date.now() - execution.started_at;

  return (
    <div className="wf-execution-panel">
      <div className="wf-exec-header">
        <div className={`wf-exec-title is-${execution.status}`}>
          {statusIcon}
          <span>Execution · {statusText}</span>
          <span className="wf-exec-duration">{(duration / 1000).toFixed(1)}s</span>
        </div>
        <button className="wf-exec-close" onClick={onClose} aria-label="Close execution log">
          <X size={16} />
        </button>
      </div>
      <div className="wf-exec-body">
        <div className="wf-exec-nodes">
          {workflow.nodes.map((node) => {
            const result = execution.node_results[node.id];
            const status = result?.status || 'idle';
            return (
              <div key={node.id} className={`wf-exec-node ${status}`}>
                <span className="wf-exec-node-name">{node.name}</span>
                <span className="wf-exec-node-status">{status}</span>
                {result?.duration ? <span className="wf-exec-node-duration">{result.duration}ms</span> : null}
                {result?.error ? <span className="wf-exec-node-error">{result.error}</span> : null}
              </div>
            );
          })}
          {workflow.nodes.length === 0 && <div className="wf-exec-logs-empty">No nodes in this workflow.</div>}
        </div>
        <div className="wf-exec-logs">
          <div className="wf-exec-logs-header">Execution Log</div>
          <div className="wf-exec-logs-list">
            {execution.logs.map((log, i) => (
              <div key={i} className={`wf-exec-log ${log.level}`}>
                <span className="wf-exec-log-time">{new Date(log.timestamp).toLocaleTimeString()}</span>
                <span className="wf-exec-log-msg">{log.message}</span>
              </div>
            ))}
            {execution.logs.length === 0 && (
              <div className="wf-exec-logs-empty">Run the workflow to see execution logs.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
