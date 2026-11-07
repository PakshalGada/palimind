import { useCallback, useEffect, useState } from 'react';
import { CalendarClock, Clock, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { api } from '../../../api';
import { useApp } from '../../../AppContext';
import { Button, Toggle } from '../../../ui/primitives';
import RoutineBuilder from './RoutineBuilder';
import type { AgentListItem, Routine, Team } from '../../../types';
import './AutomationsView.css';

function relTime(ts?: number | null): string {
  if (!ts) return 'never';
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function AutomationsView({
  agents,
  teams,
}: {
  agents: AgentListItem[];
  teams: Team[];
}) {
  const { addToast, refreshOverview } = useApp();
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [builder, setBuilder] = useState<Partial<Routine> | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await api.routines.list();
      setRoutines(data.routines || []);
    } catch {
      // best effort
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const toggle = async (routine: Routine) => {
    const res = await api.routines.update(routine.id, { enabled: !routine.enabled });
    if (res.error) addToast(res.error, { tone: 'error' });
    await refresh();
  };

  const run = async (routine: Routine) => {
    const res = await api.routines.run(routine.id);
    if (res.error) addToast(res.error, { tone: 'error' });
    else {
      addToast(`Running ${routine.name}`, { tone: 'success' });
      void refreshOverview();
      await refresh();
    }
  };

  const remove = async (routine: Routine) => {
    await api.routines.remove(routine.id);
    await refresh();
  };

  return (
    <div className="ag-automations">
      <div className="ag-automations__bar">
        <p className="ag-automations__hint">
          Repeating work. Routines run on demand or on a schedule.
        </p>
        <div className="ag-automations__actions">
          <button type="button" className="ag-quiet-btn" onClick={() => void refresh()}>
            <RefreshCw size={13} /> Refresh
          </button>
          <Button size="sm" variant="secondary" onClick={() => setBuilder({ run_mode: 'manual', enabled: true })}>
            <Plus size={13} /> New routine
          </Button>
        </div>
      </div>

      <div className="ag-automations__list">
        {loading ? (
          <p className="ag-activity__empty">Loading routines…</p>
        ) : routines.length === 0 ? (
          <p className="ag-activity__empty">No routines yet.</p>
        ) : (
          routines.map((routine) => (
            <article key={routine.id} className="ag-routine">
              <span className="ag-routine__icon">
                <CalendarClock size={16} />
              </span>
              <div className="ag-routine__id">
                <span className="ag-routine__name">{routine.name}</span>
                <span className="ag-routine__meta">
                  {routine.target_type} · {routine.run_mode}
                  {routine.schedule ? ` · ${routine.schedule}` : ''} · last {relTime(routine.last_run_at)}
                </span>
              </div>
              <Toggle
                title="Enabled"
                checked={routine.enabled}
                onChange={() => void toggle(routine)}
              />
              <button type="button" className="ag-quiet-btn" onClick={() => void run(routine)}>
                <Clock size={12} /> Run
              </button>
              <button
                type="button"
                className="ag-icon-btn ag-routine__delete"
                title="Delete routine"
                aria-label="Delete routine"
                onClick={() => void remove(routine)}
              >
                <Trash2 size={13} />
              </button>
            </article>
          ))
        )}
      </div>

      <RoutineBuilder
        draft={builder}
        agents={agents}
        teams={teams}
        onClose={() => setBuilder(null)}
        onSaved={() => {
          setBuilder(null);
          void refresh();
          void refreshOverview();
        }}
        onError={(message) => addToast(message, { tone: 'error' })}
      />
    </div>
  );
}
