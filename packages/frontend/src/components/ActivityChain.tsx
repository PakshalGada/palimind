import { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  Bot,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  FileText,
  GitMerge,
  Globe,
  Info,
  MessageSquare,
  Network,
  Search,
  ShieldAlert,
  ShieldCheck,
  Shuffle,
  Sparkles,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { useApp, type ActivityStep } from '../AppContext';
import AgentAvatar from './AgentAvatar';
import Thinking, { type ThinkingVariant } from './Thinking';
import './ActivityChain.css';

const MODE_ICON: Record<string, LucideIcon> = {
  llm: MessageSquare,
  document: FileText,
  moe: Network,
  agent: Bot,
};

/** Same motion language, a different mark per mode. */
const MODE_THINKING: Record<string, ThinkingVariant> = {
  llm: 'orbit',
  document: 'trace',
  moe: 'bars',
  deep_research: 'mesh',
  agent: 'ripple',
};

const STEP_ICON: Record<string, LucideIcon> = {
  mode: Info,
  info: Info,
  graph: Network,
  search: Search,
  docs: FileText,
  reason: Brain,
  thought: Brain,
  route: Shuffle,
  briefing: Globe,
  plan: Network,
  agent: Bot,
  synthesis: GitMerge,
  verify: ShieldCheck,
  tool: Wrench,
  result: Check,
  approval: ShieldAlert,
  answer: Sparkles,
  error: AlertTriangle,
};

const THOUGHT_MESSAGES: Record<string, string[]> = {
  thinking: [
    'Analyzing your request',
    'Understanding context',
    'Identifying patterns',
    'Reasoning through the problem',
  ],
  tool: [
    'Exploring options',
    'Gathering information',
    'Processing data',
    'Evaluating results',
  ],
  success: ['Finalizing', 'Almost there'],
  error: ['Encountered an issue', 'Adjusting approach'],
};

const GENERIC_TEXTS = new Set(['Thinking...', 'working…', '']);

function ThoughtStream({ thinkingText, state }: { thinkingText: string; state: string }) {
  const [displayText, setDisplayText] = useState(thinkingText || 'working…');
  const [visible, setVisible] = useState(true);

  const isGeneric = !thinkingText || GENERIC_TEXTS.has(thinkingText);

  useEffect(() => {
    if (!isGeneric) {
      setVisible(false);
      const t1 = setTimeout(() => {
        setDisplayText(thinkingText);
        setVisible(true);
      }, 180);
      return () => clearTimeout(t1);
    }

    const messages = THOUGHT_MESSAGES[state] || THOUGHT_MESSAGES.thinking;
    let index = 0;

    const showNext = () => {
      setVisible(false);
      setTimeout(() => {
        index = (index + 1) % messages.length;
        setDisplayText(messages[index]);
        setVisible(true);
      }, 200);
    };

    setDisplayText(messages[0]);
    setVisible(true);

    const interval = setInterval(showNext, 2800);
    return () => clearInterval(interval);
  }, [isGeneric, state]);

  return (
    <span className={`ac-thought${visible ? ' ac-thought--visible' : ''}`}>{displayText}</span>
  );
}

export default function ActivityChain() {
  const { activity, thinkingText } = useApp();
  const [collapsed, setCollapsed] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  });

  if (!activity) return null;

  const ModeIcon = MODE_ICON[activity.mode] ?? Info;
  const variant = MODE_THINKING[activity.mode] ?? 'orbit';

  const pulseState = activity.steps.some((s) => s.status === 'error')
    ? 'error'
    : activity.steps.some((s) => s.status === 'active' && s.kind === 'tool')
      ? 'tool'
      : activity.steps.length > 0 && activity.steps.every((s) => s.status === 'done')
        ? 'success'
        : 'thinking';

  return (
    <div className="ac-card">
      <div className="ac-header">
        <div className="ac-header-left">
          {activity.seed ? (
            <AgentAvatar seed={activity.seed} thinking size={20} />
          ) : (
            <ModeIcon size={16} className="ac-mode-icon" />
          )}
          <span className="ac-title-main">{activity.title}</span>
          {activity.subtitle && <span className="ac-subtitle">{activity.subtitle}</span>}
        </div>
        <div className="ac-header-right">
          <span className="ac-status">
            <Thinking variant={variant} size={16} />
            <ThoughtStream thinkingText={thinkingText} state={pulseState} />
          </span>
          <button
            type="button"
            className="ac-collapse"
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? 'Expand' : 'Collapse'}
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>

      {!collapsed && activity.steps.length > 0 && (
        <div className="ac-steps" ref={scrollRef}>
          {activity.steps.map((step, i) => (
            <StepNode key={step.id} step={step} isLast={i === activity.steps.length - 1} />
          ))}
        </div>
      )}
    </div>
  );
}

function StepNode({ step, isLast }: { step: ActivityStep; isLast: boolean }) {
  const [toggled, setToggled] = useState<boolean | null>(null);
  const open = toggled ?? step.status === 'active';
  const Icon = STEP_ICON[step.kind] ?? Info;
  const hasBody = Boolean(step.detail || step.children?.length);

  return (
    <div className={`ac-step ac-step--${step.status}`}>
      <span className={`ac-node ac-node--${step.status}`}>
        {step.status === 'active' ? (
          <Thinking variant="beacon" size={11} />
        ) : step.status === 'done' ? (
          <Check size={12} />
        ) : step.status === 'error' ? (
          <AlertTriangle size={12} />
        ) : (
          <Icon size={12} />
        )}
      </span>
      <div className="ac-body">
        <button
          type="button"
          className="ac-step-head"
          onClick={() => hasBody && setToggled(!open)}
        >
          <Icon size={13} className="ac-step-icon" />
          <span className="ac-step-title">{step.title}</span>
          {step.status === 'done' && <Check size={12} className="ac-step-done" />}
          {hasBody && (open ? <ChevronDown size={12} /> : <ChevronRight size={12} />)}
        </button>
        {open && step.detail && <div className="ac-step-detail">{step.detail}</div>}
        {open && step.children?.length ? (
          <div className="ac-children">
            {step.children.map((c) => (
              <StepNode key={c.id} step={c} isLast={false} />
            ))}
          </div>
        ) : null}
      </div>
      {!isLast && <span className="ac-line" />}
    </div>
  );
}
