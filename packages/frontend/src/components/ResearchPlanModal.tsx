import { useEffect, useState } from 'react';
import { GripVertical, Plus, Trash2 } from 'lucide-react';
import { api } from '../api';
import { useApp } from '../AppContext';
import { Modal } from '../ui/primitives';
import type { ResearchSubTopic } from '../types';
import './ResearchPlanModal.css';

function normalizePlan(plan: ResearchSubTopic[]): ResearchSubTopic[] {
  return plan.map((item, index) => ({
    subtopic_id: index + 1,
    title: item.title || `Research Area ${index + 1}`,
    research_question: item.research_question || '',
    search_queries: item.search_queries ?? [],
  }));
}

export default function ResearchPlanModal() {
  const { addToast } = useApp();
  const [open, setOpen] = useState(false);
  const [planId, setPlanId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [plan, setPlan] = useState<ResearchSubTopic[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as
        | { plan_id?: string; plan?: ResearchSubTopic[]; query?: string }
        | undefined;
      if (!detail?.plan_id) return;
      setPlanId(detail.plan_id);
      setPlan(normalizePlan(detail.plan ?? []));
      setQuery(detail.query ?? '');
      setOpen(true);
    };
    window.addEventListener('palimind:research-plan', handler);
    return () => window.removeEventListener('palimind:research-plan', handler);
  }, []);

  const patch = (index: number, changes: Partial<ResearchSubTopic>) => {
    setPlan((prev) => prev.map((item, i) => (i === index ? { ...item, ...changes } : item)));
  };

  const addSubtopic = () => {
    setPlan((prev) => [
      ...prev,
      {
        subtopic_id: prev.length + 1,
        title: `Research Area ${prev.length + 1}`,
        research_question: '',
        search_queries: [],
      },
    ]);
  };

  const removeSubtopic = (index: number) => {
    setPlan((prev) => normalizePlan(prev.filter((_, i) => i !== index)));
  };

  const approve = async () => {
    if (!planId || busy) return;
    const cleaned = plan.filter((p) => p.title.trim() || p.research_question.trim());
    if (cleaned.length === 0) {
      addToast('Add at least one sub-topic before starting.');
      return;
    }
    setBusy(true);
    try {
      const res = await api.research.approve(planId, normalizePlan(cleaned));
      if (res.error) {
        addToast(res.error);
      } else {
        addToast('Research started');
        setOpen(false);
      }
    } catch {
      addToast('Could not start research.');
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!planId || busy) return;
    setBusy(true);
    try {
      await api.research.cancel(planId);
    } catch {
      // best effort
    } finally {
      setBusy(false);
      setOpen(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={cancel}
      title="Review Research Plan"
      subtitle={query ? `Deep research on “${query}”` : 'Review and edit the research sub-topics before execution.'}
      width={760}
      footer={
        <div className="research-plan-footer">
          <button type="button" className="ui-btn ui-btn--ghost ui-btn--sm" onClick={cancel} disabled={busy}>
            Cancel research
          </button>
          <button type="button" className="ui-btn ui-btn--primary ui-btn--sm" onClick={approve} disabled={busy}>
            {busy ? 'Starting…' : 'Approve & run research'}
          </button>
        </div>
      }
    >
      <p className="research-plan-hint">
        Edit any sub-topic, adjust the search queries, or add your own. The pipeline will run all
        approved sub-topics in parallel.
      </p>
      <div className="research-plan-list">
        {plan.map((item, index) => (
          <div key={index} className="research-plan-item">
            <div className="research-plan-item-head">
              <GripVertical size={14} className="research-plan-grip" />
              <span className="research-plan-index">{index + 1}</span>
              <input
                className="research-plan-title-input"
                value={item.title}
                placeholder="Sub-topic title"
                onChange={(e) => patch(index, { title: e.target.value })}
              />
              <button
                type="button"
                className="ui-icon-btn"
                title="Remove sub-topic"
                aria-label={`Remove sub-topic ${index + 1}`}
                onClick={() => removeSubtopic(index)}
                disabled={plan.length <= 1}
              >
                <Trash2 size={14} />
              </button>
            </div>
            <textarea
              className="research-plan-question"
              value={item.research_question}
              placeholder="The specific question this sub-topic investigates"
              rows={2}
              onChange={(e) => patch(index, { research_question: e.target.value })}
            />
            <input
              className="research-plan-queries"
              value={item.search_queries.join(', ')}
              placeholder="Search queries, comma-separated"
              onChange={(e) =>
                patch(index, {
                  search_queries: e.target.value
                    .split(',')
                    .map((q) => q.trim())
                    .filter(Boolean),
                })
              }
            />
          </div>
        ))}
      </div>
      <button type="button" className="research-plan-add" onClick={addSubtopic}>
        <Plus size={14} /> Add sub-topic
      </button>
    </Modal>
  );
}
