import { Columns2, Gavel, ShieldCheck, Wand2 } from 'lucide-react';
import { useApp } from '../../AppContext';
import { api } from '../../api';
import { resolveScope } from '../../lib/scope';
import { runCommand } from '../../commands/registry';
import { Dialog } from '../../ui/primitives';
import { routeLabel } from '../../utils/chatRouting';
import './ChatModelDialog.css';

const MODES = [
  {
    id: 'default' as const,
    label: 'Default',
    detail: 'One model, fastest and cheapest.',
  },
  {
    id: 'moe' as const,
    label: 'Council',
    detail: 'Mixture of Experts: parallel workers plus a synthesizer.',
  },
  {
    id: 'deep_research' as const,
    label: 'Deep Research',
    detail: 'Plan, research in parallel, then write a cited report.',
  },
];

export default function ChatModelDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const {
    currentModel,
    llmSubMode,
    setLlmSubMode,
    autoRoute,
    setAutoRoute,
    activeView,
    activeProjectId,
    selectedAgentId,
  } = useApp();

  const scope = resolveScope(activeView, {
    agentId: selectedAgentId,
    projectId: activeProjectId,
  });

  const choose = (mode: (typeof MODES)[number]['id']) => {
    setLlmSubMode(mode);
    void api.config.setMoe({ moe_sub_mode: mode }, scope).catch(() => undefined);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Model intelligence"
      subtitle={`Current model: ${currentModel || 'Loading…'}`}
      width={620}
    >
      <div className="chat-model">
        <section>
          <h3>Reasoning mode</h3>
          <div className="chat-model__modes">
            {MODES.map((mode) => (
              <button
                key={mode.id}
                type="button"
                className={`chat-model__mode${llmSubMode === mode.id ? ' is-active' : ''}`}
                onClick={() => choose(mode.id)}
              >
                <span>{mode.label}</span>
                <small>{mode.detail}</small>
              </button>
            ))}
          </div>
        </section>

        <label className="chat-model__auto">
          <span className="chat-model__auto-icon"><Wand2 size={15} /></span>
          <span>
            <strong>Auto-route</strong>
            <small>
              Pick the mode per prompt: research goes to Deep Research, complex analysis to Council, simple prompts stay Default.
            </small>
          </span>
          <input
            type="checkbox"
            checked={autoRoute}
            onChange={(event) => setAutoRoute(event.target.checked)}
          />
        </label>

        <section className="chat-model__actions">
          <h3>Answer quality</h3>
          <button
            type="button"
            onClick={() => {
              window.dispatchEvent(
                new CustomEvent('palimind:prefill-composer', {
                  detail: {
                    text: 'Critique the previous answer. List errors, unsupported claims, missing evidence and edge cases, then give a corrected version.',
                  },
                }),
              );
              onClose();
            }}
          >
            <Gavel size={15} />
            <span>
              <strong>Critic pass</strong>
              <small>Review the last answer and revise it.</small>
            </span>
          </button>
          <button
            type="button"
            onClick={() => {
              runCommand('chat.compare-models');
              onClose();
            }}
          >
            <Columns2 size={15} />
            <span>
              <strong>Compare models</strong>
              <small>Run the same prompt side by side.</small>
            </span>
          </button>
        </section>

        <div className="chat-model__foot">
          <ShieldCheck size={13} />
          Routing and model choice stay on this machine.
          <span>Auto route is {autoRoute ? 'on' : 'off'} · {routeLabel(llmSubMode)}</span>
        </div>
      </div>
    </Dialog>
  );
}
