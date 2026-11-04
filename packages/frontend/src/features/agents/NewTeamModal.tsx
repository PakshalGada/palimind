import { useEffect, useMemo, useState } from 'react';
import { Users } from 'lucide-react';
import { api } from '../../api';
import type { AgentListItem, Team, TeamMode } from '../../types';
import { Button, Chip, Field, Modal, Select, TextArea, TextInput } from '../../ui/primitives';

export default function NewTeamModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (team?: Team) => void;
}) {
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [displayName, setDisplayName] = useState('');
  const [description, setDescription] = useState('');
  const [mode, setMode] = useState<TeamMode>('manager');
  const [selected, setSelected] = useState<string[]>([]);
  const [manager, setManager] = useState('');
  const [charter, setCharter] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setDisplayName('');
    setDescription('');
    setMode('manager');
    setSelected([]);
    setManager('');
    setCharter('');
    setError('');
    api.agents
      .list()
      .then((d) => setAgents((d.agents || []).filter((a) => a.enabled)))
      .catch(() => {});
  }, [open]);

  const handle = useMemo(
    () =>
      displayName
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 64),
    [displayName],
  );

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      if (!next.includes(manager)) setManager(next[0] || '');
      return next;
    });
  };

  const create = async () => {
    setError('');
    if (!displayName.trim()) {
      setError('Give the team a name.');
      return;
    }
    if (selected.length < 1) {
      setError('Pick at least one teammate.');
      return;
    }
    setSaving(true);
    try {
      const res = await api.teams.create({
        name: handle || 'my-team',
        display_name: displayName.trim(),
        description,
        mode,
        charter,
        manager_agent_id: manager || selected[0],
        members: selected.map((id) => ({ agent_id: id, role: '', manager: id === manager })),
      });
      if (res.error) setError(res.error);
      else {
        window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
        onCreated(res.team);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setSaving(false);
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create a team"
      subtitle="A group of specialists with a manager, a shared thread and shared notes."
      width={720}
      footer={
        <div className="team-modal__foot">
          <Button size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" disabled={saving} onClick={() => void create()}>
            <Users size={13} /> {saving ? 'Creating…' : 'Create team'}
          </Button>
        </div>
      }
    >
      <div className="team-modal">
        {error && <div className="onboard__error">{error}</div>}
        <div className="onboard__grid2">
          <Field label="Team name">
            <TextInput
              value={displayName}
              placeholder="Growth Team"
              onChange={(e) => setDisplayName(e.target.value)}
              autoFocus
            />
          </Field>
          <Field label="Handle" hint="Letters, digits, dashes.">
            <TextInput value={handle} readOnly />
          </Field>
        </div>
        <Field label="Description">
          <TextArea
            rows={2}
            value={description}
            placeholder="Plans launches, writes copy, checks the data."
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <Field label="How should the team work?">
          <Select value={mode} onChange={(e) => setMode(e.target.value as TeamMode)}>
            <option value="manager">Manager — one agent delegates and combines results</option>
            <option value="roundtable">Roundtable — everyone works in parallel</option>
            <option value="chain">Chain — each member builds on the previous step</option>
          </Select>
        </Field>
        <Field label="Teammates" hint="Pick the agents that belong to this team.">
          <div className="team-modal__agents">
            {agents.length === 0 && <p className="ah-panel__empty">Create an agent first.</p>}
            {agents.map((agent) => {
              const on = selected.includes(agent.id);
              return (
                <button
                  key={agent.id}
                  type="button"
                  className={`team-modal__agent${on ? ' is-on' : ''}`}
                  onClick={() => toggle(agent.id)}
                >
                  <span className="team-modal__agent-name">{agent.display_name || agent.name}</span>
                  <span className="team-modal__agent-role">{agent.title || agent.name}</span>
                  {on && <Chip tone="accent">member</Chip>}
                </button>
              );
            })}
          </div>
        </Field>
        {selected.length > 1 && (
          <Field label="Manager" hint="The manager delegates and writes the final answer.">
            <Select value={manager} onChange={(e) => setManager(e.target.value)}>
              {selected.map((id) => {
                const agent = agents.find((a) => a.id === id);
                return (
                  <option key={id} value={id}>
                    {agent?.display_name || agent?.name || id}
                  </option>
                );
              })}
            </Select>
          </Field>
        )}
        <Field label="Charter" hint="Team-wide instructions injected into the manager prompt.">
          <TextArea
            rows={3}
            value={charter}
            placeholder="Always cite sources. Keep the final answer under 800 words."
            onChange={(e) => setCharter(e.target.value)}
          />
        </Field>
      </div>
    </Modal>
  );
}
