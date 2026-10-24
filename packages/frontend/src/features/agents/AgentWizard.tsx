import { useEffect, useMemo, useState } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { api } from '../../api';
import AgentAvatar from '../../components/AgentAvatar';
import CronEditor from '../../components/CronEditor';
import type { AgentDefinition, SkillMeta, ToolMeta } from '../../types';
import {
  Badge,
  Button,
  Chip,
  Field,
  Modal,
  SegmentedControl,
  TextArea,
  TextInput,
  Toggle,
} from '../../ui/primitives';
import AvatarCustomizer from './AvatarCustomizer';
import ModelPicker from './ModelPicker';
import { EMPTY_DEF } from './types';

const STEPS = [
  { label: 'Identity', blurb: 'Who is this bot?' },
  { label: 'Purpose', blurb: 'What is it here to do?' },
  { label: 'Capabilities', blurb: 'What tools can it use?' },
  { label: 'Autonomy', blurb: 'How independent is it?' },
  { label: 'Scope', blurb: 'What knowledge can it reach?' },
  { label: 'Review', blurb: 'Confirm and create' },
] as const;

const PERSONALITY_PRESETS = ['Professional', 'Friendly', 'Direct', 'Academic', 'Creative', 'Analytical'];

const AUTONOMY_OPTIONS = [
  {
    value: 'supervised',
    title: 'Fully supervised',
    desc: 'Asks before every tool call.',
    threshold: 1.0,
    icon: ShieldAlert,
  },
  {
    value: 'semi',
    title: 'Semi-autonomous',
    desc: 'Asks only for medium / high-risk actions.',
    threshold: 0.5,
    icon: Shield,
  },
  {
    value: 'high',
    title: 'High autonomy',
    desc: 'Only asks for high-risk / irreversible actions.',
    threshold: 0.1,
    icon: ShieldCheck,
  },
] as const;

const MEMORY_OPTIONS = [
  { value: 'shared', title: 'Shared global memory', desc: 'Learns alongside your other bots.', scope: 'field' as const },
  { value: 'private', title: 'Private memory only', desc: 'Keeps everything to this bot.', scope: 'session' as const },
  { value: 'project', title: 'Project-scoped memory', desc: 'Remembers the active project.', scope: 'field' as const },
] as const;

const KNOWLEDGE_OPTIONS = [
  { value: 'personal', title: 'Personal', desc: "Only this bot's own notes and memory." },
  { value: 'project', title: 'Project', desc: 'The active knowledge base / project.' },
  { value: 'shared', title: 'Shared', desc: 'Every knowledge base you have added.' },
] as const;

function tierMeta(tier: number): { label: string; tone: 'success' | 'warn' | 'danger' } {
  if (tier >= 3) return { label: 'high risk', tone: 'danger' };
  if (tier === 2) return { label: 'medium', tone: 'warn' };
  return { label: 'safe', tone: 'success' };
}

export default function AgentWizard({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id?: string) => void;
}) {
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<Partial<AgentDefinition>>(EMPTY_DEF);
  const [tools, setTools] = useState<Record<string, ToolMeta>>({});
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [fieldPaths, setFieldPaths] = useState<string[]>([]);
  const [toolQuery, setToolQuery] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setDraft({ ...EMPTY_DEF });
    setError('');
    setToolQuery('');
  }, [open]);

  useEffect(() => {
    api.agents
      .tools()
      .then((d) => setTools(d.tools || {}))
      .catch(() => {});
    api.agents
      .skills()
      .then((d) => setSkills(d.skills || []))
      .catch(() => {});
    api.fields
      .list()
      .then((d) => setFieldPaths(d.fields || []))
      .catch(() => {});
  }, []);

  const patch = (p: Partial<AgentDefinition>) => setDraft((d) => ({ ...d, ...p }));

  const toggleTool = (id: string) => {
    const cur = new Set(draft.tools || []);
    if (cur.has(id)) cur.delete(id);
    else cur.add(id);
    patch({ tools: Array.from(cur) });
  };

  const toggleSkill = (id: string) => {
    const cur = new Set(draft.skills || []);
    if (cur.has(id)) cur.delete(id);
    else cur.add(id);
    patch({ skills: Array.from(cur) });
  };

  const toggleField = (path: string) => {
    const cur = new Set(draft.context_fields || []);
    if (cur.has(path)) cur.delete(path);
    else cur.add(path);
    patch({ context_fields: Array.from(cur) });
  };

  const groupedTools = useMemo(() => {
    const byTier: Record<number, ToolMeta[]> = { 1: [], 2: [], 3: [] };
    const q = toolQuery.trim().toLowerCase();
    for (const t of Object.values(tools)) {
      if (q && !t.id.toLowerCase().includes(q) && !t.description.toLowerCase().includes(q)) continue;
      (byTier[t.tier] ||= []).push(t);
    }
    return byTier;
  }, [tools, toolQuery]);

  const nameValid = /^[\w-]{1,64}$/.test(draft.name || '');

  const autonomy = AUTONOMY_OPTIONS.find((o) => o.value === (draft.autonomy_level || 'semi')) ?? AUTONOMY_OPTIONS[1];
  const memory = MEMORY_OPTIONS.find((o) => o.value === (draft.memory_mode || 'shared')) ?? MEMORY_OPTIONS[0];
  const knowledge =
    KNOWLEDGE_OPTIONS.find((o) => o.value === (draft.knowledge_access || 'personal')) ?? KNOWLEDGE_OPTIONS[0];

  const create = async () => {
    if (!nameValid) {
      setError('Name must be 1–64 chars: letters, digits, underscore or dash.');
      setStep(0);
      return;
    }
    if (draft.run_mode === 'scheduled' && !draft.schedule) {
      setError('Set a cron schedule before creating a scheduled bot.');
      setStep(3);
      return;
    }
    if (draft.run_mode === 'watcher' && !draft.watcher_pattern) {
      setError('Set a watcher pattern (e.g. *.md) before creating a watcher bot.');
      setStep(3);
      return;
    }
    setSaving(true);
    setError('');
    const composed = [
      draft.goal ? `Mission: ${draft.goal}` : '',
      draft.custom_instructions || '',
      draft.personality_style ? `Communication style: ${draft.personality_style}` : '',
      draft.description ? `About: ${draft.description}` : '',
    ]
      .filter(Boolean)
      .join('\n\n');
    const payload: Partial<AgentDefinition> = {
      ...draft,
      system_prompt: composed || draft.system_prompt || '',
      color_seed: draft.name || 'palimind',
      human_in_loop_threshold: autonomy.threshold,
      memory_scope: memory.scope,
      tier_policy: draft.shell_access ? 'all' : draft.write_access ? 'tier1+2' : 'tier1',
      schedule: draft.run_mode === 'scheduled' ? draft.schedule || '' : null,
      watcher_pattern: draft.run_mode === 'watcher' ? draft.watcher_pattern || '' : null,
    };
    try {
      const res = await api.agents.create(payload);
      if (res.error) setError(res.error);
      else onCreated(res.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setSaving(false);
  };

  const footer = (
    <div className="ax-wizard__foot">
      <div className="ax-wizard__progress">
        <div className="ax-wizard__segments">
          {STEPS.map((s, i) => (
            <span key={s.label} className={`ax-wizard__seg${i <= step ? ' is-on' : ''}`} />
          ))}
        </div>
        <span className="ax-wizard__step-label">
          {step + 1}/{STEPS.length} · {STEPS[step].label}
        </span>
      </div>
      <div className="ax-wizard__actions">
        {step > 0 && (
          <Button size="sm" onClick={() => setStep((s) => Math.max(0, s - 1))}>
            <ChevronLeft size={13} /> Back
          </Button>
        )}
        {step < STEPS.length - 1 ? (
          <Button
            variant="primary"
            size="sm"
            disabled={step === 0 && !nameValid}
            onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}
          >
            Next <ChevronRight size={13} />
          </Button>
        ) : (
          <Button variant="primary" size="sm" disabled={saving || !nameValid} onClick={create}>
            <Sparkles size={13} /> {saving ? 'Creating…' : 'Create Bot'}
          </Button>
        )}
      </div>
    </div>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create a bot"
      subtitle={`${STEPS[step].label} — ${STEPS[step].blurb}`}
      width={760}
      footer={footer}
    >
      {/* Step 1 — Identity */}
      {step === 0 && (
        <div className="ax-form">
          <div className="ax-form__grid">
            <Field
              label="Name"
              hint={
                draft.name && !nameValid
                  ? 'Use letters, digits, dashes or underscores only (no spaces).'
                  : 'Required · letters, digits, dashes or underscores.'
              }
            >
              <TextInput
                value={draft.name || ''}
                placeholder="researcher"
                onChange={(e) => patch({ name: e.target.value })}
                autoFocus
              />
            </Field>
            <Field label="Title / role" hint="Shown under the name, e.g. Research Analyst.">
              <TextInput
                value={draft.title || ''}
                placeholder="Research Analyst"
                onChange={(e) => patch({ title: e.target.value })}
              />
            </Field>
          </div>

          <Field label="Avatar">
            <AvatarCustomizer value={draft} onChange={(p) => patch(p)} />
          </Field>

          <Field label="Short description" hint="1–2 sentences shown in lists.">
            <TextArea
              rows={2}
              value={draft.description || ''}
              placeholder="Tracks markets and turns noisy sources into a daily brief."
              onChange={(e) => patch({ description: e.target.value })}
            />
          </Field>

          <Field label="Personality / style" hint="Pick a preset or write your own.">
            <div className="ax-chips">
              {PERSONALITY_PRESETS.map((p) => (
                <button
                  key={p}
                  type="button"
                  className={`ax-pickchip${draft.personality_style === p ? ' is-on' : ''}`}
                  onClick={() => patch({ personality_style: draft.personality_style === p ? '' : p })}
                >
                  {p}
                </button>
              ))}
            </div>
            <TextArea
              rows={3}
              value={draft.personality_style || ''}
              placeholder="e.g. Warm but concise. Challenges assumptions politely."
              onChange={(e) => patch({ personality_style: e.target.value })}
            />
          </Field>
        </div>
      )}

      {/* Step 2 — Purpose & Instructions */}
      {step === 1 && (
        <div className="ax-form">
          <Field label="Primary goal / standing mission" hint="What this bot is mainly for.">
            <TextArea
              rows={3}
              value={draft.goal || ''}
              placeholder="Keep me ahead of AI research and send a concise brief every morning."
              onChange={(e) => patch({ goal: e.target.value })}
            />
          </Field>

          <Field
            label="Custom instructions"
            hint="Detailed system prompt — behaviours, constraints and output format."
          >
            <TextArea
              rows={8}
              value={draft.custom_instructions || ''}
              placeholder="You are a rigorous research analyst. Always cite sources and flag uncertainty…"
              onChange={(e) => patch({ custom_instructions: e.target.value })}
            />
          </Field>

          <section className="ax-form__section">
            <h4 className="ax-form__title">Memory settings</h4>
            <div className="ax-option-list">
              {MEMORY_OPTIONS.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  className={`ax-option${(draft.memory_mode || 'shared') === o.value ? ' is-on' : ''}`}
                  onClick={() => patch({ memory_mode: o.value })}
                >
                  <span className="ax-option__radio" aria-hidden />
                  <span className="ax-option__body">
                    <span className="ax-option__title">{o.title}</span>
                    <span className="ax-option__desc">{o.desc}</span>
                  </span>
                </button>
              ))}
            </div>
          </section>

          <Field label="Model" hint="Leave empty to use the workspace default.">
            <ModelPicker value={draft.model || ''} onChange={(v) => patch({ model: v })} />
          </Field>
        </div>
      )}

      {/* Step 3 — Capabilities */}
      {step === 2 && (
        <div className="ax-tools">
          <div className="ax-tools__bar">
            <TextInput
              placeholder="Search tools…"
              value={toolQuery}
              onChange={(e) => setToolQuery(e.target.value)}
            />
            <Chip>{(draft.tools || []).length} selected</Chip>
          </div>

          {skills.length > 0 && (
            <div className="ax-tier">
              <div className="ax-tier__head">
                <span className="ax-tier__name">Skills</span>
                <span className="ax-tier__sub">Reusable behaviour bundles</span>
              </div>
              <div className="ax-skill-grid">
                {skills.map((s) => {
                  const on = (draft.skills || []).includes(s.id);
                  return (
                    <button
                      type="button"
                      key={s.id}
                      className={`ax-skill${on ? ' is-on' : ''}`}
                      onClick={() => toggleSkill(s.id)}
                      title={s.instructions}
                    >
                      <span className="ax-skill__top">
                        <span className="ax-skill__name">{s.name}</span>
                        {s.tools.length > 0 && <Badge tone="muted">{s.tools.length} tools</Badge>}
                      </span>
                      <span className="ax-skill__desc">{s.description}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {[1, 2, 3].map((tier) => {
            const items = groupedTools[tier] || [];
            if (items.length === 0) return null;
            const risk = tierMeta(tier);
            return (
              <div key={tier} className="ax-tier">
                <div className="ax-tier__head">
                  <span className="ax-tier__name">
                    Tier {tier} <Badge tone={risk.tone}>{risk.label}</Badge>
                  </span>
                  <span className="ax-tier__sub">
                    {tier === 1
                      ? 'Read-only and safe'
                      : tier === 2
                        ? 'Writes or executes — may ask for approval'
                        : 'Privileged system access'}
                  </span>
                </div>
                <div className="ax-tool-grid">
                  {items.map((t) => {
                    const on = (draft.tools || []).includes(t.id);
                    return (
                      <button
                        type="button"
                        key={t.id}
                        className={`ax-tool${on ? ' is-on' : ''}`}
                        onClick={() => toggleTool(t.id)}
                        title={t.description}
                      >
                        <span className="ax-tool__top">
                          <span className="ax-tool__name">{t.id}</span>
                          {t.requires_approval && <Badge tone="warn">approval</Badge>}
                        </span>
                        <span className="ax-tool__desc">{t.description}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}

          <section className="ax-form__section">
            <h4 className="ax-form__title">Access gates</h4>
            <Toggle
              title="Write access"
              description="Create or modify files in the workspace."
              checked={!!draft.write_access}
              onChange={(v) => patch({ write_access: v })}
            />
            <Toggle
              title="Shell access"
              description="Run sandboxed shell commands (tier 3)."
              checked={!!draft.shell_access}
              onChange={(v) => patch({ shell_access: v })}
            />
            <Toggle
              title="Self-critique"
              description="Run a reflection pass that reviews and improves the answer."
              checked={!!draft.self_critique}
              onChange={(v) => patch({ self_critique: v })}
            />
          </section>
        </div>
      )}

      {/* Step 4 — Autonomy & Behavior */}
      {step === 3 && (
        <div className="ax-form">
          <section className="ax-form__section">
            <h4 className="ax-form__title">Autonomy level</h4>
            <div className="ax-option-list">
              {AUTONOMY_OPTIONS.map((o) => {
                const Icon = o.icon;
                return (
                  <button
                    key={o.value}
                    type="button"
                    className={`ax-option${(draft.autonomy_level || 'semi') === o.value ? ' is-on' : ''}`}
                    onClick={() => patch({ autonomy_level: o.value })}
                  >
                    <Icon size={16} className="ax-option__icon" />
                    <span className="ax-option__body">
                      <span className="ax-option__title">{o.title}</span>
                      <span className="ax-option__desc">{o.desc}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="ax-form__section">
            <h4 className="ax-form__title">Proactive behavior</h4>
            <Toggle
              title="Can this bot message me first?"
              description="Allow it to start conversations without a prompt."
              checked={!!draft.proactive_message_first}
              onChange={(v) => patch({ proactive_message_first: v })}
            />
            <Toggle
              title="Morning brief"
              description="Send a short summary at the start of the day."
              checked={!!draft.morning_brief}
              onChange={(v) => patch({ morning_brief: v })}
            />
            <Field label="Watch certain sources" hint="Comma-separated sites, feeds or folders.">
              <TextInput
                value={(draft.watch_sources || []).join(', ')}
                placeholder="arxiv.org, techcrunch.com, inbox"
                onChange={(e) =>
                  patch({
                    watch_sources: e.target.value
                      .split(',')
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
              />
            </Field>
          </section>

          <section className="ax-form__section">
            <h4 className="ax-form__title">Schedule & limits</h4>
            <Field label="Working hours / schedule" hint="Optional, e.g. Mon–Fri 09:00–18:00.">
              <TextInput
                value={draft.working_hours || ''}
                placeholder="Mon–Fri 09:00–18:00"
                onChange={(e) => patch({ working_hours: e.target.value })}
              />
            </Field>
            <Field label="Trigger">
              <SegmentedControl
                value={draft.run_mode || 'on_demand'}
                onChange={(v) => patch({ run_mode: v })}
                options={[
                  { value: 'on_demand', label: 'On demand' },
                  { value: 'scheduled', label: 'Scheduled' },
                  { value: 'watcher', label: 'Watcher' },
                  { value: 'webhook', label: 'Webhook' },
                ]}
              />
            </Field>
            {draft.run_mode === 'scheduled' && (
              <Field label="Cron schedule">
                <CronEditor value={draft.schedule || ''} onChange={(v) => patch({ schedule: v })} />
              </Field>
            )}
            {draft.run_mode === 'watcher' && (
              <Field label="Watcher pattern (glob)" hint="Runs whenever a matching file changes.">
                <TextInput
                  value={draft.watcher_pattern || ''}
                  placeholder="*.md"
                  onChange={(e) => patch({ watcher_pattern: e.target.value })}
                />
              </Field>
            )}
            <div className="ax-form__grid">
              <Field label="Max concurrent runs" hint="Resource limit for parallel work.">
                <TextInput
                  type="number"
                  min={1}
                  max={16}
                  value={draft.max_concurrent_runs ?? 1}
                  onChange={(e) =>
                    patch({ max_concurrent_runs: Math.max(1, Math.min(16, parseInt(e.target.value) || 1)) })
                  }
                />
              </Field>
              <Field label="Max steps per run">
                <TextInput
                  type="number"
                  min={1}
                  value={draft.max_iterations ?? 15}
                  onChange={(e) => patch({ max_iterations: parseInt(e.target.value) || 1 })}
                />
              </Field>
            </div>
          </section>
        </div>
      )}

      {/* Step 5 — Knowledge & Scope */}
      {step === 4 && (
        <div className="ax-form">
          <section className="ax-form__section">
            <h4 className="ax-form__title">Access level</h4>
            <div className="ax-option-list">
              {KNOWLEDGE_OPTIONS.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  className={`ax-option${(draft.knowledge_access || 'personal') === o.value ? ' is-on' : ''}`}
                  onClick={() => patch({ knowledge_access: o.value })}
                >
                  <span className="ax-option__radio" aria-hidden />
                  <span className="ax-option__body">
                    <span className="ax-option__title">{o.title}</span>
                    <span className="ax-option__desc">{o.desc}</span>
                  </span>
                </button>
              ))}
            </div>
          </section>

          <section className="ax-form__section">
            <h4 className="ax-form__title">Knowledge bases / projects</h4>
            {fieldPaths.length === 0 ? (
              <div className="ax-tier__empty">No knowledge bases added yet.</div>
            ) : (
              <div className="ax-scope-list">
                {fieldPaths.map((p) => {
                  const on = (draft.context_fields || []).includes(p);
                  return (
                    <label key={p} className={`ax-scope${on ? ' is-on' : ''}`}>
                      <input type="checkbox" checked={on} onChange={() => toggleField(p)} />
                      <span className="ax-scope__path">{p}</span>
                    </label>
                  );
                })}
              </div>
            )}
          </section>

          <Toggle
            title="Can create new knowledge"
            description="Allow the bot to save new notes, findings and documents."
            checked={!!draft.can_create_knowledge}
            onChange={(v) => patch({ can_create_knowledge: v })}
          />
        </div>
      )}

      {/* Step 6 — Review & Create */}
      {step === 5 && (
        <div className="ax-review">
          <div className="ax-review__hero">
            <AgentAvatar
              config={draft.avatar_config}
              type={draft.avatar_type === 'upload' ? 'upload' : 'bot'}
              upload={draft.avatar_upload}
              size={72}
            />
            <div className="ax-review__hero-body">
              <div className="ax-review__name">{draft.name || 'Untitled bot'}</div>
              <div className="ax-review__title">{draft.title || 'No role set'}</div>
              {draft.description && <div className="ax-review__desc">{draft.description}</div>}
            </div>
          </div>

          <div className="ax-review__grid">
            <div className="ax-review__row">
              <span className="ax-review__label">Tools</span>
              <div className="ax-review__value">
                {(draft.tools || []).length === 0 ? (
                  <span className="ax-review__muted">None selected</span>
                ) : (
                  <div className="ax-review__tags">
                    {(draft.tools || []).map((id) => {
                      const t = tools[id];
                      const risk = t ? tierMeta(t.tier) : null;
                      return (
                        <span key={id} className="ax-review__tag">
                          <span>{id}</span>
                          {risk && <Badge tone={risk.tone}>{risk.label}</Badge>}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
            <div className="ax-review__row">
              <span className="ax-review__label">Autonomy</span>
              <span className="ax-review__value">{autonomy.title}</span>
            </div>
            <div className="ax-review__row">
              <span className="ax-review__label">Memory</span>
              <span className="ax-review__value">{memory.title}</span>
            </div>
            <div className="ax-review__row">
              <span className="ax-review__label">Knowledge access</span>
              <span className="ax-review__value">
                {knowledge.title}
                {(draft.context_fields || []).length > 0 &&
                  ` · ${(draft.context_fields || []).length} source${
                    (draft.context_fields || []).length === 1 ? '' : 's'
                  }`}
              </span>
            </div>
            <div className="ax-review__row">
              <span className="ax-review__label">Proactive</span>
              <span className="ax-review__value">
                {[
                  draft.proactive_message_first && 'Messages first',
                  draft.morning_brief && 'Morning brief',
                  (draft.watch_sources || []).length > 0 &&
                    `Watches ${(draft.watch_sources || []).length} source${
                      (draft.watch_sources || []).length === 1 ? '' : 's'
                    }`,
                ]
                  .filter(Boolean)
                  .join(' · ') || 'On demand only'}
              </span>
            </div>
            <div className="ax-review__row">
              <span className="ax-review__label">Schedule</span>
              <span className="ax-review__value">
                {draft.working_hours || draft.run_mode || 'on_demand'}
              </span>
            </div>
            <div className="ax-review__row">
              <span className="ax-review__label">Limits</span>
              <span className="ax-review__value">
                {draft.max_concurrent_runs ?? 1} concurrent · {draft.max_iterations ?? 15} steps/run
              </span>
            </div>
          </div>
        </div>
      )}

      {error && <div className="ax-error-text ax-wizard__error">{error}</div>}
    </Modal>
  );
}
