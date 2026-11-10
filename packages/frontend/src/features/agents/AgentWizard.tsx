import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ChevronLeft, ChevronRight, Sparkles } from 'lucide-react';
import { api } from '../../api';
import AgentAvatar from '../../components/AgentAvatar';
import type { AgentDefinition, AgentListItem } from '../../types';
import { Button, Field, Modal, SegmentedControl, TextArea, TextInput } from '../../ui/primitives';
import AvatarCustomizer from './AvatarCustomizer';
import ModelPicker from './ModelPicker';
import { EMPTY_DEF } from './types';
import { AGENT_TEMPLATES, PERSONALITY_PRESETS, composeSystemPrompt, uniqueHandle } from './options';

const STEPS = [
  { label: 'Identity', blurb: 'Who is this teammate?' },
  { label: 'How it thinks', blurb: 'Pick a model and create it.' },
] as const;

const DEFAULTS: Partial<AgentDefinition> = {
  provider: 'ollama',
  tier_policy: 'all',
  write_access: true,
  shell_access: true,
  tool_pack: 'auto',
  tools: [],
  autonomy_level: 'semi',
  planning_mode: 'auto',
  self_critique: true,
  reasoning_effort: 'auto',
  memory_mode: 'private',
};

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
  const [draft, setDraft] = useState<Partial<AgentDefinition>>({ ...EMPTY_DEF, ...DEFAULTS });
  const [allAgents, setAllAgents] = useState<AgentListItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [handleTouched, setHandleTouched] = useState(false);
  const [firstTask, setFirstTask] = useState('');
  const [readiness, setReadiness] = useState<{ local: boolean; opencode: boolean } | null>(null);

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setDraft({ ...EMPTY_DEF, ...DEFAULTS });
    setError('');
    setHandleTouched(false);
    setFirstTask('');
    api.agents
      .list()
      .then((data) => setAllAgents(data.agents || []))
      .catch(() => {});
    api.agents
      .setupStatus()
      .then((status) =>
        setReadiness({
          local: Boolean(status.local?.ready),
          opencode: Boolean(status.opencode?.ready),
        }),
      )
      .catch(() => setReadiness(null));
  }, [open]);

  const patch = (next: Partial<AgentDefinition>) => setDraft((current) => ({ ...current, ...next }));

  const existingHandles = useMemo(() => allAgents.map((agent) => agent.name), [allAgents]);
  const displayName = (draft.display_name || '').trim();
  const handle = (draft.name || '').trim();
  const handleValid = /^[\w-]{1,64}$/.test(handle);
  const provider = draft.provider || 'ollama';

  const changeDisplayName = (value: string) => {
    const next: Partial<AgentDefinition> = { display_name: value };
    if (!handleTouched && value.trim()) next.name = uniqueHandle(value, existingHandles);
    patch(next);
  };

  const changeHandle = (value: string) => {
    setHandleTouched(true);
    patch({ name: value.toLowerCase().replace(/[^\w-]+/g, '-').slice(0, 64) });
  };

  const applyTemplate = (templateId: string) => {
    const template = AGENT_TEMPLATES.find((item) => item.id === templateId);
    if (!template) return;
    const label =
      template.id === 'blank'
        ? draft.display_name || ''
        : template.config.display_name || template.name;
    setDraft({
      ...EMPTY_DEF,
      ...DEFAULTS,
      ...template.config,
      display_name: label,
      name: label ? uniqueHandle(label, existingHandles) : '',
      // Every agent gets every tool; templates only shape the prompt.
      tools: [],
      tool_pack: 'auto',
      tier_policy: 'all',
      write_access: true,
      shell_access: true,
      unrestricted_tools: true,
    });
    setHandleTouched(false);
    setError('');
  };

  const validate = (): string => {
    if (!displayName) return 'Give your teammate a name.';
    if (!handleValid) return 'Handle must be 1–64 letters, digits, dashes or underscores.';
    if (existingHandles.some((name) => name.toLowerCase() === handle.toLowerCase())) {
      return `The handle @${handle} is already taken.`;
    }
    if (provider === 'opencode' && readiness?.opencode === false) {
      return 'OpenCode needs an API key. Add it in Settings → OpenCode, or choose a local model.';
    }
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
      schema_version: draft.schema_version ?? 3,
      provider,
      tools: [],
      tool_pack: 'auto',
      tier_policy: 'all',
      write_access: true,
      shell_access: true,
      unrestricted_tools: true,
      autonomy_level: draft.autonomy_level || 'semi',
    };
    try {
      const result = await api.agents.create(payload);
      if (result.error) {
        setError(result.error);
      } else {
        if (result.id && firstTask.trim()) {
          try {
            localStorage.setItem(`palimind:agent-first-task:${result.id}`, firstTask.trim());
          } catch {
            // storage is optional
          }
        }
        onCreated(result.id);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSaving(false);
    }
  };

  const footer = (
    <div className="ax-wizard__foot">
      <div className="ax-wizard__progress">
        <div className="ax-wizard__segments">
          {STEPS.map((item, index) => (
            <button
              key={item.label}
              type="button"
              className={`ax-wizard__seg${index <= step ? ' is-on' : ''}`}
              onClick={() => {
                if (index <= step || !validate()) setStep(index);
              }}
              title={item.label}
              aria-label={`Go to ${item.label}`}
            />
          ))}
        </div>
        <span className="ax-wizard__step-label">
          {step + 1}/{STEPS.length} · {STEPS[step].label}
        </span>
      </div>
      <div className="ax-wizard__actions">
        {step > 0 && (
          <Button size="sm" onClick={() => setStep(0)}>
            <ChevronLeft size={13} /> Back
          </Button>
        )}
        {step === 0 ? (
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              const problem = validate();
              if (problem) setError(problem);
              else {
                setError('');
                setStep(1);
              }
            }}
          >
            Next <ChevronRight size={13} />
          </Button>
        ) : (
          <Button variant="primary" size="sm" disabled={saving} onClick={() => void create()}>
            <Sparkles size={13} /> {saving ? 'Creating…' : 'Create agent'}
          </Button>
        )}
      </div>
    </div>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create an agent"
      subtitle={`${STEPS[step].label} — ${STEPS[step].blurb}`}
      width={720}
      footer={footer}
    >
      {error && (
        <div className="ax-settings__warning ax-wizard__banner" role="alert">
          <AlertTriangle size={14} />
          <span>{error}</span>
        </div>
      )}

      {step === 0 && (
        <div className="ax-form">
          <section className="ax-form__section">
            <h4 className="ax-form__title">Start from a role</h4>
            <div className="ax-template-grid">
              {AGENT_TEMPLATES.map((template) => (
                <button
                  key={template.id}
                  type="button"
                  className={`ax-template${
                    draft.title === template.config.title && template.id !== 'blank' ? ' is-on' : ''
                  }`}
                  onClick={() => applyTemplate(template.id)}
                >
                  <span className="ax-template__name">{template.name}</span>
                  <span className="ax-template__tag">{template.tagline}</span>
                </button>
              ))}
            </div>
          </section>

          <div className="ax-form__grid">
            <Field label="Name" hint="Shown in the sidebar and chat.">
              <TextInput
                value={draft.display_name || ''}
                placeholder="Ada"
                autoFocus
                onChange={(event) => changeDisplayName(event.target.value)}
              />
            </Field>
            <Field label="Handle" hint="Unique @mention.">
              <TextInput
                value={draft.name || ''}
                placeholder="ada"
                onChange={(event) => changeHandle(event.target.value)}
              />
            </Field>
          </div>
          <Field label="Role" hint="One line for the roster.">
            <TextInput
              value={draft.title || ''}
              placeholder="Research Analyst"
              onChange={(event) => patch({ title: event.target.value })}
            />
          </Field>

          <Field label="Personality">
            <div className="ax-chips">
              {PERSONALITY_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  className={`ax-pickchip${draft.personality_style === preset ? ' is-on' : ''}`}
                  onClick={() =>
                    patch({ personality_style: draft.personality_style === preset ? '' : preset })
                  }
                >
                  {preset}
                </button>
              ))}
            </div>
          </Field>

          <details className="ax-advanced" open>
            <summary>Avatar and color</summary>
            <AvatarCustomizer value={draft} onChange={(next) => patch(next)} />
          </details>
        </div>
      )}

      {step === 1 && (
        <div className="ax-form">
          <div className="ax-review__hero">
            <AgentAvatar
              config={draft.avatar_config}
              type={draft.avatar_type === 'upload' ? 'upload' : 'bot'}
              upload={draft.avatar_upload}
              size={56}
            />
            <div className="ax-review__hero-body">
              <div className="ax-review__name">{displayName}</div>
              <div className="ax-review__title">
                {draft.title || 'Agent'} · @{handle}
              </div>
              <div className="ax-review__desc">
                Every tool is available. Risky actions still ask for approval.
              </div>
            </div>
          </div>

          <div className="ax-form__grid">
            <Field label="Runs on" hint="Local is private and free. OpenCode uses your key.">
              <SegmentedControl<string>
                value={provider}
                onChange={(value) => patch({ provider: value, model: '' })}
                options={[
                  { value: 'ollama', label: 'Local' },
                  { value: 'opencode', label: 'OpenCode' },
                ]}
              />
            </Field>
            <Field label="Model" hint="Empty uses the workspace default.">
              <ModelPicker value={draft.model || ''} onChange={(model) => patch({ model })} />
            </Field>
          </div>

          {provider === 'opencode' && readiness?.opencode === false && (
            <div className="ax-settings__warning" role="status">
              <AlertTriangle size={14} />
              <span>
                No OpenCode key found. Add one in Settings → OpenCode, or switch to Local.
              </span>
              <Button
                size="sm"
                onClick={() =>
                  window.dispatchEvent(
                    new CustomEvent('palimind:open-settings', { detail: { section: 'opencode' } }),
                  )
                }
              >
                Open settings
              </Button>
            </div>
          )}

          <Field
            label="First task (optional)"
            hint="Placed in the composer when the chat opens, so you can review it."
          >
            <TextArea
              rows={3}
              value={firstTask}
              onChange={(event) => setFirstTask(event.target.value)}
              placeholder="Introduce yourself, then…"
            />
          </Field>
        </div>
      )}
    </Modal>
  );
}
