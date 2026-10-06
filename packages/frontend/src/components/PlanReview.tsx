import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, ListChecks, Play, Plus, X } from 'lucide-react';
import { api } from '../api';
import { useApp } from '../AppContext';
import MermaidPreview from './MermaidPreview';
import { Badge, Button, Chip, EmptyState, Field, Modal, Select, TextArea, TextInput } from '../ui/primitives';
import type { AgentPlan, PlanStep, PlanTemplate } from '../types';
import './PlanReview.css';

/**
 * Plan-then-execute review (Phase 4.4). Generates a plan, lets the user edit
 * individual steps, approves/rejects it (unblocking a run waiting in review
 * mode) and executes it with rollback. Open with `palimind:open-plan-review`
 * or automatically when a run emits `palimind:plan-pending`.
 */
export default function PlanReview() {
  const { selectedAgentId, addToast } = useApp();
  const [open, setOpen] = useState(false);
  const [plans, setPlans] = useState<AgentPlan[]>([]);
  const [selected, setSelected] = useState<AgentPlan | null>(null);
  const [templates, setTemplates] = useState<PlanTemplate[]>([]);
  const [template, setTemplate] = useState('');
  const [task, setTask] = useState('');
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const res = await api.agents.plans.list();
      setPlans(res.plans || []);
    } catch {
      // best effort
    }
  }, []);

  useEffect(() => {
    const onOpen = () => {
      setOpen(true);
      void refresh();
    };
    const onPending = async (e: Event) => {
      const detail = (e as CustomEvent).detail as { plan_id?: string };
      if (!detail?.plan_id) return;
      setPendingId(detail.plan_id);
      setOpen(true);
      try {
        const plan = await api.agents.plans.get(detail.plan_id);
        if (!('error' in plan)) setSelected(plan);
      } catch {
        // ignore
      }
      void refresh();
    };
    window.addEventListener('palimind:open-plan-review', onOpen);
    window.addEventListener('palimind:plan-pending', onPending);
    return () => {
      window.removeEventListener('palimind:open-plan-review', onOpen);
      window.removeEventListener('palimind:plan-pending', onPending);
    };
  }, [refresh]);

  useEffect(() => {
    api.agents.plans
      .templates()
      .then((r) => setTemplates(r.templates || []))
      .catch(() => {});
    void refresh();
  }, [refresh]);

  const mermaid = useMemo(() => {
    if (!selected || selected.steps.length === 0) return '';
    const lines = ['flowchart TD'];
    selected.steps.forEach((s, i) => {
      const label = `${i + 1}. ${s.title || 'Step'}`.replace(/"/g, "'");
      lines.push(`  S${i}[${JSON.stringify(label)}]`);
      if (i > 0) lines.push(`  S${i - 1} --> S${i}`);
    });
    return lines.join('\n');
  }, [selected]);

  const patchStep = (index: number, changes: Partial<PlanStep>) => {
    if (!selected) return;
    const steps = selected.steps.map((s, i) => (i === index ? { ...s, ...changes } : s));
    setSelected({ ...selected, steps });
  };

  const generate = async () => {
    if (!task.trim()) {
      addToast('Describe the task to plan.');
      return;
    }
    setBusy(true);
    try {
      const res = await api.agents.plans.create(task.trim(), {
        template: template || undefined,
        agent_id: selectedAgentId || undefined,
      });
      setSelected(res.plan);
      await refresh();
    } catch (e) {
      addToast(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };

  const save = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const res = await api.agents.plans.update(selected.id, { steps: selected.steps });
      if (!('error' in res)) {
        setSelected(res);
        addToast('Plan saved.');
        await refresh();
      }
    } catch (e) {
      addToast(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };

  const decide = async (approved: boolean) => {
    if (!selected) return;
    setBusy(true);
    try {
      if (pendingId === selected.id) {
        await api.agents.plans.approve(selected.id, approved, selected.steps);
        setPendingId(null);
        addToast(approved ? 'Plan approved — the run will continue.' : 'Plan rejected.');
      } else {
        await api.agents.plans.update(selected.id, {
          steps: selected.steps,
          status: approved ? 'approved' : 'rejected',
        });
        addToast(approved ? 'Plan approved.' : 'Plan rejected.');
      }
      await refresh();
    } catch (e) {
      addToast(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };

  const execute = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const res = await api.agents.plans.execute(selected.id, true);
      if (res.plan) {
        setSelected(res.plan);
        addToast(`Plan ${res.plan.status}.`);
      } else if (res.error) {
        addToast(res.error);
      }
      await refresh();
    } catch (e) {
      addToast(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };

  return (
    <Modal
      open={open}
      onClose={() => setOpen(false)}
      title="Plan review"
      subtitle="Review, edit and approve a plan before the agent executes it"
      width={940}
    >
      <div className="pr">
        <div className="pr-sidebar">
          <div className="pr-new">
            <Field label="New plan">
              <TextInput
                placeholder="Task to plan…"
                value={task}
                onChange={(e) => setTask(e.target.value)}
              />
            </Field>
            <Field label="Template">
              <Select value={template} onChange={(e) => setTemplate(e.target.value)}>
                <option value="">None</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Button size="sm" variant="primary" disabled={busy} onClick={generate}>
              <Plus size={14} /> Generate
            </Button>
          </div>
          <div className="pr-list">
            {plans.length === 0 && <div className="pr-list__empty">No plans yet.</div>}
            {plans.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`pr-item${selected?.id === p.id ? ' is-active' : ''}`}
                onClick={() => setSelected(p)}
              >
                <span className="pr-item__task">{p.task || '(untitled)'}</span>
                <span className="pr-item__meta">
                  <Badge tone={p.status === 'approved' || p.status === 'completed' ? 'success' : 'muted'}>
                    {p.status}
                  </Badge>
                  <span>{p.steps.length} steps</span>
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="pr-main">
          {!selected && (
            <EmptyState
              icon={<ListChecks size={22} />}
              title="No plan selected"
              description="Generate a plan or pick one on the left."
            />
          )}
          {selected && (
            <>
              {pendingId === selected.id && (
                <div className="pr-pending">
                  An agent run is waiting for your approval of this plan.
                </div>
              )}
              <div className="pr-main__head">
                <Chip>{selected.steps.length} steps</Chip>
                <Badge tone="muted">{selected.status}</Badge>
                <div className="pr-main__actions">
                  <Button size="sm" disabled={busy} onClick={save}>
                    Save edits
                  </Button>
                  <Button size="sm" variant="primary" disabled={busy} onClick={() => decide(true)}>
                    <Check size={14} /> Approve
                  </Button>
                  <Button size="sm" variant="danger" disabled={busy} onClick={() => decide(false)}>
                    <X size={14} /> Reject
                  </Button>
                  <Button size="sm" disabled={busy} onClick={execute}>
                    <Play size={14} /> Execute
                  </Button>
                </div>
              </div>

              <div className="pr-steps">
                {selected.steps.map((s, i) => (
                  <div key={s.id ?? i} className={`pr-step pr-step--${s.status}`}>
                    <div className="pr-step__num">{i + 1}</div>
                    <div className="pr-step__fields">
                      <TextInput
                        value={s.title}
                        placeholder="Step title"
                        onChange={(e) => patchStep(i, { title: e.target.value })}
                      />
                      <TextArea
                        rows={2}
                        value={s.description}
                        placeholder="What this step does"
                        onChange={(e) => patchStep(i, { description: e.target.value })}
                      />
                      <div className="pr-step__row">
                        <TextInput
                          value={s.tool}
                          placeholder="tool (optional)"
                          onChange={(e) => patchStep(i, { tool: e.target.value })}
                        />
                        <Badge tone={s.status === 'done' ? 'success' : s.status === 'failed' ? 'danger' : 'muted'}>
                          {s.status}
                        </Badge>
                      </div>
                      {s.result && <div className="pr-step__result">{s.result}</div>}
                    </div>
                  </div>
                ))}
              </div>

              {mermaid && (
                <div className="pr-flow">
                  <MermaidPreview code={mermaid} />
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}
