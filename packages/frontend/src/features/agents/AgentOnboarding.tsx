import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Sparkles,
  Shield,
  Wrench,
  UserRound,
  X,
} from 'lucide-react';
import { api } from '../../api';
import AgentAvatar from '../../components/AgentAvatar';
import type { AgentDefinition, AgentListItem, ToolMeta } from '../../types';
import { Button, Chip, Field, TextArea, TextInput, Toggle } from '../../ui/primitives';
import AvatarCustomizer from './AvatarCustomizer';
import type { BotAvatarConfig } from '../../bots/config';
import { EMPTY_DEF } from './types';
import {
  AGENT_TEMPLATES,
  AUTONOMY_OPTIONS,
  PERSONALITY_PRESETS,
  SHELL_TOOLS,
  TOOL_PACK_OPTIONS,
  WRITE_TOOLS,
  composeSystemPrompt,
  uniqueHandle,
} from './options';
import './AgentOnboarding.css';

const STEPS = [
  { id: 'role', label: 'Choose a role', icon: Sparkles },
  { id: 'identity', label: 'Identity', icon: UserRound },
  { id: 'abilities', label: 'Abilities', icon: Wrench },
  { id: 'review', label: 'Review', icon: Check },
] as const;

const DEFAULTS: Partial<AgentDefinition> = {
  planning_mode: 'auto',
  self_critique: true,
  reasoning_effort: 'auto',
  max_iterations: 20,
  memory_mode: 'private',
  tool_pack: 'auto',
  tier_policy: 'tier1+2',
};

export default function AgentOnboarding({
  open,
  onClose,
  onCreated,
  initialAgent,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id?: string) => void;
  initialAgent?: AgentListItem | null;
}) {
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<Partial<AgentDefinition>>({ ...EMPTY_DEF, ...DEFAULTS });
  const [tools, setTools] = useState<Record<string, ToolMeta>>({});
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [query, setQuery] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [handleTouched, setHandleTouched] = useState(false);

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setError('');
    setQuery('');
    setHandleTouched(false);
    setDraft(
      initialAgent
        ? { ...EMPTY_DEF, ...initialAgent }
        : { ...EMPTY_DEF, ...DEFAULTS },
    );
  }, [open, initialAgent]);

  useEffect(() => {
    if (!open) return;
    api.agents.tools().then((d) => setTools(d.tools || {})).catch(() => {});
    api.agents.list().then((d) => setAgents(d.agents || [])).catch(() => {});
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const patch = (p: Partial<AgentDefinition>) => setDraft((d) => ({ ...d, ...p }));

  const existingHandles = useMemo(() => agents.map((a) => a.name), [agents]);
  const displayName = (draft.display_name || '').trim();
  const handle = (draft.name || '').trim();
  const handleValid = /^[\w-]{1,64}$/.test(handle);
  const chosenPack = draft.tool_pack || 'auto';

  const applyTemplate = (id: string) => {
    const template = AGENT_TEMPLATES.find((t) => t.id === id);
    if (!template) return;
    const label = template.id === 'blank' ? '' : template.name;
    setDraft({
      ...EMPTY_DEF,
      ...DEFAULTS,
      ...template.config,
      display_name: label,
      name: label ? uniqueHandle(label, existingHandles) : '',
    });
    setHandleTouched(false);
    setError('');
    setStep(1);
  };

  const changeDisplayName = (value: string) => {
    const next: Partial<AgentDefinition> = { display_name: value };
    if (!handleTouched && value.trim()) next.name = uniqueHandle(value, existingHandles);
    patch(next);
  };

  const changeHandle = (value: string) => {
    setHandleTouched(true);
    patch({ name: value.toLowerCase().replace(/[^\w-]+/g, '-').slice(0, 64) });
  };

  const toggleTool = (id: string) => {
    const cur = new Set(draft.tools || []);
    if (cur.has(id)) cur.delete(id);
    else cur.add(id);
    const next: Partial<AgentDefinition> = { tools: Array.from(cur) };
    if (WRITE_TOOLS.some((t) => cur.has(t))) next.write_access = true;
    if (SHELL_TOOLS.some((t) => cur.has(t))) next.shell_access = true;
    if ((tools[id]?.tier || 1) >= 3) {
      next.tier_policy = 'all';
      next.write_access = true;
      next.shell_access = true;
    } else if ((tools[id]?.tier || 1) === 2 && draft.tier_policy === 'tier1') {
      next.tier_policy = 'tier1+2';
    }
    patch(next);
  };

  const validate = (): string => {
    if (!displayName) return 'Give your agent a name.';
    if (!handleValid) return 'Handle must be 1–64 letters, digits, dashes or underscores.';
    if (existingHandles.some((n) => n.toLowerCase() === handle.toLowerCase() && n !== initialAgent?.name))
      return `The handle @${handle} is already taken.`;
    return '';
  };

  const create = async () => {
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    setError('');
    const payload: Partial<AgentDefinition> = {
      ...draft,
      name: handle,
      display_name: displayName,
      system_prompt: composeSystemPrompt(draft),
      // Without a schema version the backend treats the body as a legacy
      // definition and resets autonomy_level / memory_mode to defaults.
      schema_version: draft.schema_version ?? 3,
      tool_pack: chosenPack,
    };
    try {
      const res = initialAgent
        ? await api.agents.update(initialAgent.id, payload)
        : await api.agents.create(payload);
      if (res.error) setError(res.error);
      else onCreated(res.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setSaving(false);
  };

  const curatedTools = useMemo(() => {
    const q = query.trim().toLowerCase();
    const all = Object.values(tools).filter(
      (t) => !q || t.id.toLowerCase().includes(q) || t.description.toLowerCase().includes(q),
    );
    return all.sort((a, b) => a.tier - b.tier || a.id.localeCompare(b.id)).slice(0, 80);
  }, [tools, query]);

  if (!open) return null;

  const previewAvatar = (
    <AgentAvatar
      config={draft.avatar_config as BotAvatarConfig}
      type={draft.avatar_type === 'upload' ? 'upload' : 'bot'}
      upload={draft.avatar_upload}
      size={96}
    />
  );

  return createPortal(
    <div className="onboard" role="dialog" aria-modal="true" aria-label="Create an agent">
      <div className="onboard__shell">
        <aside className="onboard__rail">
          <div className="onboard__brand">
            <span className="onboard__brand-dot" />
            <span>New teammate</span>
          </div>
          <nav className="onboard__steps">
            {STEPS.map((s, i) => {
              const Icon = s.icon;
              return (
                <button
                  key={s.id}
                  type="button"
                  className={`onboard__step${i === step ? ' is-on' : ''}${i < step ? ' is-done' : ''}`}
                  onClick={() => {
                    if (i <= step || !validate()) setStep(i);
                  }}
                >
                  <span className="onboard__step-icon">
                    {i < step ? <Check size={14} /> : <Icon size={14} />}
                  </span>
                  <span>
                    <span className="onboard__step-label">{s.label}</span>
                    <span className="onboard__step-index">Step {i + 1}</span>
                  </span>
                </button>
              );
            })}
          </nav>
          <div className="onboard__rail-note">
            <Shield size={14} />
            <span>Everything stays local. You can change every setting later.</span>
          </div>
        </aside>

        <section className="onboard__main">
          <header className="onboard__head">
            <div>
              <h2 className="onboard__title">
                {initialAgent ? 'Edit teammate' : STEPS[step].label}
              </h2>
              <p className="onboard__sub">
                {step === 0 && 'Start from a ready-made role, or build one from scratch.'}
                {step === 1 && 'Give your teammate a name, a face and a voice.'}
                {step === 2 && 'Choose what it can do and how carefully it should work.'}
                {step === 3 && 'One last look before it joins your team.'}
              </p>
            </div>
            <button type="button" className="onboard__close" onClick={onClose} aria-label="Close">
              <X size={18} />
            </button>
          </header>

          {error && <div className="onboard__error">{error}</div>}

          <div className="onboard__scroll">
            {step === 0 && (
              <div className="onboard__roles">
                {AGENT_TEMPLATES.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={`onboard-role${draft.title === t.config.title && t.id !== 'blank' ? ' is-on' : ''}`}
                    onClick={() => applyTemplate(t.id)}
                  >
                    <span className="onboard-role__avatar">
                      <AgentAvatar
                        config={(t.config.avatar_config || {}) as BotAvatarConfig}
                        size={44}
                        interactive={false}
                      />
                    </span>
                    <span className="onboard-role__body">
                      <span className="onboard-role__name">{t.name}</span>
                      <span className="onboard-role__tag">{t.tagline}</span>
                    </span>
                    <ArrowRight size={15} className="onboard-role__arrow" />
                  </button>
                ))}
              </div>
            )}

            {step === 1 && (
              <div className="onboard__identity">
                <div className="onboard__preview">
                  <div className="onboard__preview-avatar">{previewAvatar}</div>
                  <div className="onboard__preview-name">{displayName || 'Your new teammate'}</div>
                  <div className="onboard__preview-role">
                    {draft.title || 'Specialist'}
                    {handle ? ` · @${handle}` : ''}
                  </div>
                  <div className="onboard__preview-chips">
                    <Chip>{chosenPack} tools</Chip>
                    <Chip tone="muted">{draft.autonomy_level || 'semi'}</Chip>
                  </div>
                </div>
                <div className="onboard__form">
                  <div className="onboard__grid2">
                    <Field label="Name" hint="Shown everywhere in the app.">
                      <TextInput
                        value={draft.display_name || ''}
                        placeholder="Ada"
                        autoFocus
                        onChange={(e) => changeDisplayName(e.target.value)}
                      />
                    </Field>
                    <Field label="Handle" hint="Unique @mention.">
                      <TextInput
                        value={draft.name || ''}
                        placeholder="ada"
                        onChange={(e) => changeHandle(e.target.value)}
                      />
                    </Field>
                  </div>
                  <Field label="Role / title" hint="One line that explains what this teammate does.">
                    <TextInput
                      value={draft.title || ''}
                      placeholder="Research Analyst"
                      onChange={(e) => patch({ title: e.target.value })}
                    />
                  </Field>
                  <Field label="About" hint="A short description for the roster.">
                    <TextArea
                      rows={3}
                      value={draft.description || ''}
                      placeholder="Finds sources, verifies claims and writes concise briefs."
                      onChange={(e) => patch({ description: e.target.value })}
                    />
                  </Field>
                  <Field label="Personality">
                    <div className="onboard__chips">
                      {PERSONALITY_PRESETS.map((p) => (
                        <button
                          key={p}
                          type="button"
                          className={`onboard__chip${draft.personality_style === p ? ' is-on' : ''}`}
                          onClick={() =>
                            patch({ personality_style: draft.personality_style === p ? '' : p })
                          }
                        >
                          {p}
                        </button>
                      ))}
                    </div>
                  </Field>
                  <details className="onboard__details" open>
                    <summary>Appearance</summary>
                    <AvatarCustomizer value={draft} onChange={(p) => patch(p)} />
                  </details>
                </div>
              </div>
            )}

            {step === 2 && (
              <div className="onboard__abilities">
                <section className="onboard__section">
                  <h3 className="onboard__section-title">Tool pack</h3>
                  <p className="onboard__section-sub">
                    Packs narrow which tools the agent may call. <strong>Auto</strong> allows every
                    tier-appropriate tool.
                  </p>
                  <div className="onboard__packs">
                    {TOOL_PACK_OPTIONS.map((pack) => {
                      const on = chosenPack === pack.value;
                      return (
                        <button
                          key={pack.value}
                          type="button"
                          className={`onboard-pack${on ? ' is-on' : ''}`}
                          onClick={() => patch({ tool_pack: pack.value as AgentDefinition['tool_pack'] })}
                        >
                          <span className="onboard-pack__name">{pack.label}</span>
                          <span className="onboard-pack__desc">{pack.desc}</span>
                        </button>
                      );
                    })}
                  </div>
                </section>

                <section className="onboard__section">
                  <h3 className="onboard__section-title">Access</h3>
                  <Toggle
                    title="Write access"
                    description="Create and edit files in the workspace and knowledge bases."
                    checked={!!draft.write_access}
                    onChange={(v) => patch({ write_access: v })}
                  />
                  <Toggle
                    title="Shell access"
                    description="Run Python and shell commands in the sandbox."
                    checked={!!draft.shell_access}
                    onChange={(v) => patch({ shell_access: v })}
                  />
                  <Toggle
                    title="Self-critique"
                    description="Review and improve the answer before delivering it."
                    checked={!!draft.self_critique}
                    onChange={(v) => patch({ self_critique: v })}
                  />
                </section>

                <section className="onboard__section">
                  <h3 className="onboard__section-title">Working style</h3>
                  <div className="onboard__autonomy">
                    {AUTONOMY_OPTIONS.map((option) => {
                      const Icon = option.icon;
                      const on = (draft.autonomy_level || 'semi') === option.value;
                      return (
                        <button
                          key={option.value}
                          type="button"
                          className={`onboard-autonomy${on ? ' is-on' : ''}`}
                          onClick={() => patch({ autonomy_level: option.value })}
                        >
                          <Icon size={15} />
                          <span>
                            <span className="onboard-autonomy__title">{option.title}</span>
                            <span className="onboard-autonomy__desc">{option.desc}</span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  <div className="onboard__grid2 onboard__grid2--top">
                    <Field label="Reasoning effort">
                      <select
                        className="ui-select"
                        value={draft.reasoning_effort || 'auto'}
                        onChange={(e) =>
                          patch({ reasoning_effort: e.target.value as AgentDefinition['reasoning_effort'] })
                        }
                      >
                        <option value="auto">Auto — adaptive</option>
                        <option value="minimal">Minimal</option>
                        <option value="standard">Standard</option>
                        <option value="high">High</option>
                        <option value="max">Max</option>
                      </select>
                    </Field>
                    <Field label="Planning">
                      <select
                        className="ui-select"
                        value={draft.planning_mode || 'auto'}
                        onChange={(e) =>
                          patch({ planning_mode: e.target.value as AgentDefinition['planning_mode'] })
                        }
                      >
                        <option value="auto">Plan automatically</option>
                        <option value="review">Plan, then ask me</option>
                        <option value="off">No plan</option>
                      </select>
                    </Field>
                  </div>
                </section>

                <section className="onboard__section">
                  <h3 className="onboard__section-title">Tools</h3>
                  <p className="onboard__section-sub">
                    {chosenPack === 'auto'
                      ? 'Auto mode still lets you pin extra tools. Selected tools are always allowed.'
                      : 'Pick exactly the tools this teammate may use.'}
                  </p>
                  <TextInput
                    placeholder="Search tools…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                  <div className="onboard__toolgrid">
                    {curatedTools.map((tool) => {
                      const on = (draft.tools || []).includes(tool.id);
                      return (
                        <button
                          key={tool.id}
                          type="button"
                          className={`onboard-tool${on ? ' is-on' : ''}`}
                          onClick={() => toggleTool(tool.id)}
                          title={tool.description}
                        >
                          <span className="onboard-tool__id">{tool.id}</span>
                          <span className="onboard-tool__tier">tier {tool.tier}</span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              </div>
            )}

            {step === 3 && (
              <div className="onboard__review">
                <div className="onboard__review-card">
                  <div className="onboard__review-head">
                    {previewAvatar}
                    <div>
                      <div className="onboard__review-name">{displayName || 'Unnamed teammate'}</div>
                      <div className="onboard__review-role">
                        {draft.title || 'Specialist'} {handle ? `· @${handle}` : ''}
                      </div>
                      <div className="onboard__preview-chips">
                        <Chip>{chosenPack}</Chip>
                        <Chip tone="muted">{draft.autonomy_level || 'semi'}</Chip>
                        {draft.write_access && <Chip tone="warn">write</Chip>}
                        {draft.shell_access && <Chip tone="warn">shell</Chip>}
                      </div>
                    </div>
                  </div>
                  <p className="onboard__review-desc">
                    {draft.description || 'No description yet.'}
                  </p>
                  <div className="onboard__review-grid">
                    <div>
                      <span className="onboard__review-label">Mission</span>
                      <p>{draft.goal || 'No standing mission — it will follow each task.'}</p>
                    </div>
                    <div>
                      <span className="onboard__review-label">Tools</span>
                      <p>
                        {(draft.tools || []).length} pinned
                        {chosenPack === 'auto' ? ' · all tier-appropriate tools' : ` · ${chosenPack} pack`}
                      </p>
                    </div>
                    <div>
                      <span className="onboard__review-label">Planning</span>
                      <p>
                        {draft.planning_mode === 'review'
                          ? 'Plan, then ask you'
                          : draft.planning_mode === 'auto'
                            ? 'Automatic'
                            : 'Off'}
                      </p>
                    </div>
                    <div>
                      <span className="onboard__review-label">Memory</span>
                      <p>{draft.memory_mode || 'private'}</p>
                    </div>
                  </div>
                  <Field label="Standing mission" hint="What should this teammate always be working toward?">
                    <TextArea
                      rows={2}
                      value={draft.goal || ''}
                      placeholder="Keep me ahead of AI research with a weekly brief."
                      onChange={(e) => patch({ goal: e.target.value })}
                    />
                  </Field>
                  <Field label="Custom instructions" hint="Optional. The system prompt is composed from these fields.">
                    <TextArea
                      rows={5}
                      value={draft.custom_instructions || ''}
                      onChange={(e) => patch({ custom_instructions: e.target.value })}
                    />
                  </Field>
                </div>
              </div>
            )}
          </div>

          <footer className="onboard__foot">
            <div className="onboard__foot-note">
              {step === 0 && 'Pick a role to continue'}
              {step === 1 && `@${handle || 'handle'}`}
              {step === 2 && `${(draft.tools || []).length} tools pinned`}
              {step === 3 && 'Ready to join your team'}
            </div>
            <div className="onboard__foot-actions">
              {step > 0 && (
                <Button size="sm" onClick={() => setStep((s) => Math.max(0, s - 1))}>
                  <ArrowLeft size={13} /> Back
                </Button>
              )}
              {step < STEPS.length - 1 ? (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => {
                    if (step === 1) {
                      const problem = validate();
                      if (problem) {
                        setError(problem);
                        return;
                      }
                    }
                    setError('');
                    setStep((s) => Math.min(STEPS.length - 1, s + 1));
                  }}
                  disabled={step === 0 && !draft.title && !draft.display_name}
                >
                  Continue <ArrowRight size={13} />
                </Button>
              ) : (
                <Button variant="primary" size="sm" disabled={saving} onClick={() => void create()}>
                  <Sparkles size={13} /> {saving ? 'Saving…' : initialAgent ? 'Save teammate' : 'Create teammate'}
                </Button>
              )}
            </div>
          </footer>
        </section>
      </div>
    </div>,
    document.body,
  );
}
