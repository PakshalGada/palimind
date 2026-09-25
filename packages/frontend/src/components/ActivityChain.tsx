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
  Loader2,
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
import './ActivityChain.css';

const MODE_ICON: Record<string, LucideIcon> = {
  llm: MessageSquare,
  document: FileText,
  moe: Network,
  agent: Bot,
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
            <Loader2 size={12} className="ac-spin" />
            {thinkingText || 'working…'}
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
          <Loader2 size={12} className="ac-spin" />
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
