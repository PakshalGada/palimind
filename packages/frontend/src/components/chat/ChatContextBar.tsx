import { useState } from 'react';
import { Brain, Columns2, Cpu, Folder, Package, Pin, ShieldCheck } from 'lucide-react';
import { useApp } from '../../AppContext';
import { collectArtifacts } from '../../utils/artifacts';
import { runCommand } from '../../commands/registry';
import ChatContextManager from './ChatContextManager';
import ChatMemoryDialog from './ChatMemoryDialog';
import ChatTrustDialog from './ChatTrustDialog';
import './ChatContextBar.css';

function leaf(path: string | null): string {
  if (!path) return 'Local';
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

export default function ChatContextBar() {
  const {
    activeView,
    currentModel,
    llmSubMode,
    activeField,
    activeProjectId,
    activeProjectName,
    sessions,
    activeSessionId,
    openWorkbench,
    responseStyle,
    setResponseStyle,
    chatMemory,
    pinnedContext,
  } = useApp();
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [trustOpen, setTrustOpen] = useState(false);

  if (activeView !== 'chat') return null;

  const session = sessions.find((item) => item.id === activeSessionId);
  const artifactCount = collectArtifacts(session?.messages).length;
  const workspace = activeProjectId
    ? activeProjectName || 'Project'
    : leaf(activeField);
  const mode =
    llmSubMode === 'moe'
      ? 'Mixture of Experts'
      : llmSubMode === 'deep_research'
        ? 'Deep Research'
        : 'Default';

  return (
    <div className="chat-context-bar" aria-label="Chat context">
      <span className="chat-context-chip" title={`Model: ${currentModel}`}>
        <Cpu size={12} />
        <span className="chat-context-chip__text">{currentModel}</span>
      </span>
      <span className="chat-context-chip" title={`Mode: ${mode}`}>
        <span className="chat-context-chip__dot" aria-hidden="true" />
        {mode}
      </span>
      <span className="chat-context-chip" title={`Workspace: ${workspace}`}>
        <Folder size={12} />
        <span className="chat-context-chip__text">{workspace}</span>
      </span>
      <button
        type="button"
        className="chat-context-chip chat-context-chip--button"
        title="Open artifacts workbench"
        onClick={() => openWorkbench('artifacts')}
      >
        <Package size={12} />
        {artifactCount} artifact{artifactCount === 1 ? '' : 's'}
      </button>
      <label className="chat-context-select" title="Response style">
        <span className="chat-context-select__label">Style</span>
        <select
          value={responseStyle}
          onChange={(event) => setResponseStyle(event.target.value as typeof responseStyle)}
          aria-label="Response style"
        >
          <option value="default">Default</option>
          <option value="brief">Brief</option>
          <option value="executive">Executive</option>
          <option value="technical">Technical</option>
          <option value="teaching">Teaching</option>
        </select>
      </label>
      <button
        type="button"
        className="chat-context-chip chat-context-chip--button"
        title="Manage chat context"
        onClick={() => setContextOpen(true)}
      >
        <Pin size={12} />
        Context{pinnedContext.length > 0 ? ` ${pinnedContext.length}` : ''}
      </button>
      <button
        type="button"
        className="chat-context-chip chat-context-chip--button"
        title="Compare two models"
        onClick={() => runCommand('chat.compare-models')}
      >
        <Columns2 size={12} />
        Compare
      </button>
      <button
        type="button"
        className="chat-context-chip chat-context-chip--button"
        title="Chat memory"
        onClick={() => setMemoryOpen(true)}
      >
        <Brain size={12} />
        Memory{chatMemory.length > 0 ? ` ${chatMemory.length}` : ''}
      </button>
      <button
        type="button"
        className="chat-context-chip chat-context-chip--button"
        title="Summarize this conversation"
        onClick={() =>
          window.dispatchEvent(
            new CustomEvent('palimind:prefill-composer', {
              detail: {
                text: 'Catch me up: summarize this conversation into decisions, action items, open questions and key facts.',
              },
            }),
          )
        }
      >
        Recap
      </button>
      <button
        type="button"
        className="chat-context-chip chat-context-chip--button chat-context-chip--quiet"
        title="Chat details"
        onClick={() => setTrustOpen(true)}
      >
        <ShieldCheck size={12} />
        Local-first
      </button>
      <ChatMemoryDialog open={memoryOpen} onClose={() => setMemoryOpen(false)} />
      <ChatContextManager open={contextOpen} onClose={() => setContextOpen(false)} />
      <ChatTrustDialog open={trustOpen} onClose={() => setTrustOpen(false)} />
    </div>
  );
}
