import { useState } from 'react';
import { Brain, Cpu, Folder, Package, Pin, Search, Share2, ShieldCheck, Wand2 } from 'lucide-react';
import { useApp } from '../../AppContext';
import { collectArtifacts } from '../../utils/artifacts';
import { memoryForScope } from '../../utils/chatMemory';
import ChatContextManager from './ChatContextManager';
import ChatContinuityDialog from './ChatContinuityDialog';
import ChatModelDialog from './ChatModelDialog';
import ChatSearchDialog from './ChatSearchDialog';
import ChatShareDialog from './ChatShareDialog';
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
    autoRoute,
  } = useApp();
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [continuityOpen, setContinuityOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [trustOpen, setTrustOpen] = useState(false);

  if (activeView !== 'chat') return null;

  const session = sessions.find((item) => item.id === activeSessionId);
  const artifactCount = collectArtifacts(session?.messages).length;
  const memoryCount = memoryForScope(chatMemory, {
    sessionId: activeSessionId,
    projectId: activeProjectId,
  }).length;
  const workspace = activeProjectId
    ? activeProjectName || 'Project'
    : leaf(activeField);
  const mode = autoRoute
    ? 'Auto'
    : llmSubMode === 'moe'
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
        title="Model intelligence, critic pass and model comparison"
        onClick={() => setModelOpen(true)}
      >
        <Wand2 size={12} />
        Intelligence
      </button>
      <button
        type="button"
        className="chat-context-chip chat-context-chip--button"
        title="Chat memory"
        onClick={() => setMemoryOpen(true)}
      >
        <Brain size={12} />
        Memory{memoryCount > 0 ? ` ${memoryCount}` : ''}
      </button>
      <button
        type="button"
        className="chat-context-chip chat-context-chip--button"
        title="Search this conversation"
        onClick={() => setSearchOpen(true)}
      >
        <Search size={12} />
        Search
      </button>
      <button
        type="button"
        className="chat-context-chip chat-context-chip--button"
        title="Recap, decisions and next steps"
        onClick={() => setContinuityOpen(true)}
      >
        Recap
      </button>
      <button
        type="button"
        className="chat-context-chip chat-context-chip--button"
        title="Share transcript, artifacts and sources"
        onClick={() => setShareOpen(true)}
      >
        <Share2 size={12} />
        Share
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
      <ChatSearchDialog open={searchOpen} onClose={() => setSearchOpen(false)} />
      <ChatContinuityDialog open={continuityOpen} onClose={() => setContinuityOpen(false)} />
      <ChatModelDialog open={modelOpen} onClose={() => setModelOpen(false)} />
      <ChatShareDialog open={shareOpen} onClose={() => setShareOpen(false)} />
      <ChatTrustDialog open={trustOpen} onClose={() => setTrustOpen(false)} />
    </div>
  );
}
