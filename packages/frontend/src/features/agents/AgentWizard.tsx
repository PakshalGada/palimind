import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api';
import CronEditor from '../../components/CronEditor';
import type { AgentDefinition, SkillMeta, ToolMeta } from '../../types';
import {
  Badge,
  Button,
  Chip,
  Field,
  Modal,
  SegmentedControl,
  Select,
  TextArea,
  TextInput,
  Toggle,
} from '../../ui/primitives';
import ModelPicker from './ModelPicker';
import { EMPTY_DEF } from './types';

const STEPS = ['Identity', 'Model', 'Tools & skills'] as const;
type WizardStep = 0 | 1 | 2;

export default function AgentWizard({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id?: string) => void;
}) {
  const [step, setStep] = useState<WizardStep>(0);
  const [draft, setDraft] = useState<Partial<AgentDefinition>>(EMPTY_DEF);
  const [tools, setTools] = useState<Record<string, ToolMeta>>({});
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [toolQuery, setToolQuery] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setDraft(EMPTY_DEF);
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

  const create = async () => {
    if (!nameValid) {
      setError('Name must be 1–64 chars: letters, digits, underscore or dash.');
      setStep(0);
      return;
    }
    setSaving(true);
    setError('');
    const payload = {
      ...draft,
      schedule: draft.schedule || null,
      watcher_pattern: draft.watcher_pattern || null,
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
      <div className="ax-wizard__dots">
        {STEPS.map((label, i) => (
          <span key={label} className={`ax-dot${i === step ? ' is-active' : ''}${i < step ? ' is-done' : ''}`}>
            {label}
          </span>
        ))}
      </div>
      <div className="ax-wizard__actions">
        {step > 0 && (
          <Button size="sm" onClick={() => setStep((s) => (s - 1) as WizardStep)}>
            Back
          </Button>
        )}
        {step < 2 ? (
          <Button
            variant="primary"
            size="sm"
            disabled={step === 0 && !nameValid}
            onClick={() => setStep((s) => (s + 1) as WizardStep)}
          >
            Next
          </Button>
        ) : (
          <Button variant="primary" size="sm" disabled={saving || !nameValid} onClick={create}>
            {saving ? 'Creating…' : 'Create agent'}
          </Button>
        )}
      </div>
    </div>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New agent"
      subtitle={STEPS[step]}
      width={720}
      footer={footer}
    >
      {step === 0 && (
        <div className="ax-form">
          <Field label="Name" hint="Letters, digits, underscore or dash. No spaces.">
            <TextInput
              value={draft.name || ''}
              placeholder="my-agent"
              onChange={(e) => patch({ name: e.target.value })}
              autoFocus
            />
          </Field>
          <Field label="System prompt" hint="The agent's persona and standing instructions.">
            <TextArea
              rows={7}
              value={draft.system_prompt || ''}
              placeholder="You are a thorough research agent that always cites sources…"
              onChange={(e) => patch({ system_prompt: e.target.value })}
            />
          </Field>
          {error && <div className="ax-error-text">{error}</div>}
        </div>
      )}

      {step === 1 && (
        <div className="ax-form">
          <Field label="Model">
            <ModelPicker value={draft.model || ''} onChange={(v) => patch({ model: v })} />
          </Field>
          <Field label={`Temperature · ${(draft.temperature ?? 0.2).toFixed(1)}`}>
            <input
              type="range"
              className="ax-range"
              min={0}
              max={2}
              step={0.1}
              value={draft.temperature ?? 0.2}
              onChange={(e) => patch({ temperature: parseFloat(e.target.value) })}
            />
          </Field>
          <Field label="Run mode">
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
            <Field label="Schedule">
              <CronEditor value={draft.schedule || ''} onChange={(v) => patch({ schedule: v })} />
            </Field>
          )}
          {draft.run_mode === 'watcher' && (
            <Field label="Watcher pattern (glob)">
              <TextInput
                value={draft.watcher_pattern || ''}
                placeholder="*.md"
                onChange={(e) => patch({ watcher_pattern: e.target.value })}
              />
            </Field>
          )}
          <div className="ax-form__grid">
            <Field label="Tier policy">
              <Select
                value={draft.tier_policy || 'tier1+2'}
                onChange={(e) => patch({ tier_policy: e.target.value as AgentDefinition['tier_policy'] })}
              >
                <option value="tier1">Tier 1 — read-only</option>
                <option value="tier1+2">Tier 1 + 2</option>
                <option value="all">All tiers</option>
              </Select>
            </Field>
            <Field label="Memory scope">
              <Select
                value={draft.memory_scope || 'field'}
                onChange={(e) => patch({ memory_scope: e.target.value as AgentDefinition['memory_scope'] })}
              >
                <option value="none">None</option>
                <option value="session">Session</option>
                <option value="field">Global</option>
              </Select>
            </Field>
          </div>
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
        </div>
      )}

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
                <span className="ax-tier__sub">Reusable behaviour bundles (add tools + instructions)</span>
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
            return (
              <div key={tier} className="ax-tier">
                <div className="ax-tier__head">
                  <span className="ax-tier__name">Tier {tier}</span>
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
          {error && <div className="ax-error-text">{error}</div>}
        </div>
      )}
    </Modal>
  );
}
