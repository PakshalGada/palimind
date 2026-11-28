import { useMemo, useState } from 'react';
import { Columns2, Gavel, Loader2, Send, ShieldCheck, Users, Wand2 } from 'lucide-react';
import { useApp } from '../../AppContext';
import { api } from '../../api';
import { resolveScope } from '../../lib/scope';
import { runCommand } from '../../commands/registry';
import { Dialog } from '../../ui/primitives';
import { formatMarkdown } from '../../utils/markdown';
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
    sessions,
    activeSessionId,
    addToast,
  } = useApp();
  const [busy, setBusy] = useState<'critic' | 'council' | null>(null);
  const [result, setResult] = useState<{
    title: string;
    body: string;
    models?: string[];
  } | null>(null);

  const session = sessions.find((item) => item.id === activeSessionId);
  const { lastUser, lastAssistant } = useMemo(() => {
    const messages = session?.messages ?? [];
    let user = '';
    let assistant = '';
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (!user && messages[index].role === 'user') user = messages[index].content;
      if (!assistant && messages[index].role !== 'user') assistant = messages[index].content;
      if (user && assistant) break;
    }
    return { lastUser: user, lastAssistant: assistant };
  }, [session?.messages]);

  const scope = resolveScope(activeView, {
    agentId: selectedAgentId,
    projectId: activeProjectId,
  });

  const choose = (mode: (typeof MODES)[number]['id']) => {
    setLlmSubMode(mode);
    void api.config.setMoe({ moe_sub_mode: mode }, scope).catch(() => undefined);
  };

  const runCritic = async () => {
    if (!lastAssistant.trim()) {
      addToast('Ask a question first — there is no answer to critique.', { tone: 'info' });
      return;
    }
    setBusy('critic');
    try {
      const data = await api.chat.critic({ text: lastAssistant, question: lastUser });
      setResult({ title: 'Critic pass', body: data.critique, models: [data.model] });
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Critic pass failed.', { tone: 'error' });
    } finally {
      setBusy(null);
    }
  };

  const runCouncil = async () => {
    const prompt = lastUser.trim() || lastAssistant.trim();
    if (!prompt) {
      addToast('Ask a question first so the council has something to answer.', { tone: 'info' });
      return;
    }
    setBusy('council');
    try {
      const data = await api.chat.council({ text: prompt });
      setResult({
        title: 'Council synthesis',
        body: data.synthesis,
        models: data.models,
      });
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Council failed.', { tone: 'error' });
    } finally {
      setBusy(null);
    }
  };

  const useResult = () => {
    if (!result) return;
    window.dispatchEvent(
      new CustomEvent('palimind:prefill-composer', { detail: { text: result.body } }),
    );
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Model intelligence"
      subtitle={`Current model: ${currentModel || 'Loading…'}`}
      width={640}
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
              Chooses a mode per prompt.
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
            disabled={busy !== null || !lastAssistant.trim()}
            onClick={() => void runCritic()}
          >
            {busy === 'critic' ? <Loader2 size={15} className="spin" /> : <Gavel size={15} />}
            <span>
              <strong>Critic pass</strong>
              <small>Review the last answer and propose a corrected version.</small>
            </span>
          </button>
          <button
            type="button"
            disabled={busy !== null || !lastUser.trim()}
            onClick={() => void runCouncil()}
          >
            {busy === 'council' ? <Loader2 size={15} className="spin" /> : <Users size={15} />}
            <span>
              <strong>Run council</strong>
              <small>Ask several local models and synthesize their answers.</small>
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

        {result && (
          <section className="chat-model__result">
            <div className="chat-model__result-head">
              <strong>{result.title}</strong>
              {result.models && (
                <span>{result.models.join(' · ')}</span>
              )}
            </div>
            <div
              className="chat-model__result-body"
              dangerouslySetInnerHTML={{ __html: formatMarkdown(result.body) }}
            />
            <button type="button" className="chat-model__use" onClick={useResult}>
              <Send size={13} />
              Use in composer
            </button>
          </section>
        )}

        <div className="chat-model__foot">
          <ShieldCheck size={13} />
          Routing and model choice stay on this machine.
          <span>Auto route is {autoRoute ? 'on' : 'off'} · {routeLabel(llmSubMode)}</span>
        </div>
      </div>
    </Dialog>
  );
}
