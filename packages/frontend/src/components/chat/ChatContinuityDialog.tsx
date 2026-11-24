import { ListChecks, MessageSquareQuote, Sparkles, Target, TriangleAlert } from 'lucide-react';
import { useApp } from '../../AppContext';
import { Dialog } from '../../ui/primitives';
import './ChatContinuityDialog.css';

const ACTIONS = [
  {
    label: 'Catch me up',
    detail: 'Decisions, actions, open questions and facts.',
    icon: Sparkles,
    prompt:
      'Catch me up on this conversation. Summarize the decisions, action items, open questions and key facts.',
  },
  {
    label: 'Decision log',
    detail: 'What was decided, why, and by whom.',
    icon: Target,
    prompt:
      'Extract the decision log from this conversation. For each decision give the decision, rationale, owner and date when stated.',
  },
  {
    label: 'Action items',
    detail: 'A checklist with owners and dates.',
    icon: ListChecks,
    prompt:
      'Extract the action items from this conversation as a checklist. Include owner and due date when stated, and flag anything unassigned.',
  },
  {
    label: 'Open questions',
    detail: 'What is still unresolved.',
    icon: TriangleAlert,
    prompt:
      'List the open questions in this conversation and what information is needed to answer each one.',
  },
  {
    label: 'Key facts',
    detail: 'Numbers, constraints and established facts.',
    icon: MessageSquareQuote,
    prompt:
      'Extract the key facts, numbers, constraints and definitions established in this conversation. Mark assumptions separately.',
  },
];

export default function ChatContinuityDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { sessions, activeSessionId } = useApp();
  const count = sessions.find((item) => item.id === activeSessionId)?.messages.length ?? 0;

  const use = (prompt: string) => {
    window.dispatchEvent(
      new CustomEvent('palimind:prefill-composer', { detail: { text: prompt } }),
    );
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Continuity"
      subtitle={`${count} messages in this chat. Turn the thread into a brief, decisions or next steps.`}
      width={580}
    >
      <div className="chat-continuity">
        {ACTIONS.map((action) => {
          const Icon = action.icon;
          return (
            <button
              key={action.label}
              type="button"
              className="chat-continuity__action"
              onClick={() => use(action.prompt)}
            >
              <span className="chat-continuity__icon">
                <Icon size={16} />
              </span>
              <span>
                <strong>{action.label}</strong>
                <small>{action.detail}</small>
              </span>
            </button>
          );
        })}
      </div>
    </Dialog>
  );
}
