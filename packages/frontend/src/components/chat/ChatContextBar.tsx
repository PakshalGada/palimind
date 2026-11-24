import { useState } from 'react';
import { Brain, Cpu, Folder, Package, ShieldCheck } from 'lucide-react';
import { useApp } from '../../AppContext';
import { collectArtifacts } from '../../utils/artifacts';
import ChatMemoryDialog from './ChatMemoryDialog';
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
  } = useApp();
  const [memoryOpen, setMemoryOpen] = useState(false);

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
      <span className="chat-context-chip chat-context-chip--quiet" title="Local-first">
        <ShieldCheck size={12} />
        Local-first
      </span>
      <ChatMemoryDialog open={memoryOpen} onClose={() => setMemoryOpen(false)} />
    </div>
  );
}
