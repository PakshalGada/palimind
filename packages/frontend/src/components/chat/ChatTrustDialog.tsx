import { Cpu, Database, Folder, Package, ShieldCheck, Trash2 } from 'lucide-react';
import { useApp } from '../../AppContext';
import { Dialog } from '../../ui/primitives';
import { collectArtifacts } from '../../utils/artifacts';
import { memoryForScope } from '../../utils/chatMemory';
import './ChatTrustDialog.css';

function leaf(path: string | null): string {
  if (!path) return 'Local workspace';
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

export default function ChatTrustDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const {
    currentModel,
    llmSubMode,
    activeField,
    activeProjectId,
    activeProjectName,
    sessions,
    activeSessionId,
    chatMemory,
    removeChatMemory,
  } = useApp();

  const session = sessions.find((item) => item.id === activeSessionId);
  const artifacts = collectArtifacts(session?.messages).length;
  const activeMemory = memoryForScope(chatMemory, {
    sessionId: activeSessionId,
    projectId: activeProjectId,
  });
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
    <Dialog
      open={open}
      onClose={onClose}
      title="Chat details"
      subtitle="What this chat is using and what it remembers."
      width={560}
    >
      <div className="chat-trust">
        <dl className="chat-trust__grid">
          <div>
            <dt><Cpu size={13} /> Model</dt>
            <dd>{currentModel || 'Not selected'}</dd>
          </div>
          <div>
            <dt>Mode</dt>
            <dd>{mode}</dd>
          </div>
          <div>
            <dt><Folder size={13} /> Workspace</dt>
            <dd>{workspace}</dd>
          </div>
          <div>
            <dt><Package size={13} /> Artifacts</dt>
            <dd>{artifacts}</dd>
          </div>
          <div>
            <dt><Database size={13} /> Memory</dt>
            <dd>{activeMemory.length} fact{activeMemory.length === 1 ? '' : 's'}</dd>
          </div>
          <div>
            <dt><ShieldCheck size={13} /> Processing</dt>
            <dd>Local-first</dd>
          </div>
        </dl>

        <section className="chat-trust__memory">
          <h3>Chat memory</h3>
          {activeMemory.length === 0 ? (
            <p>Nothing remembered yet. Add facts from the Memory button or any answer’s save menu.</p>
          ) : (
            <ul>
              {activeMemory.map((item) => (
                <li key={item.id}>
                  <span>{item.text}</span>
                  <button
                    type="button"
                    onClick={() => removeChatMemory(item.id)}
                    aria-label={`Forget: ${item.text}`}
                    title="Forget this"
                  >
                    <Trash2 size={13} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </Dialog>
  );
}
