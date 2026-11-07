import { useEffect, useState } from 'react';
import { Plus, Trash2, Users } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { useConfirm } from '../../components/ConfirmDialog';
import AgentAvatar from '../../components/AgentAvatar';
import { Button, Field, Modal, Select, TextArea, TextInput } from '../../ui/primitives';
import type { AgentListItem, Team, TeamNote } from '../../types';

export default function TeamSettingsModal({
  team,
  agents,
  open,
  onClose,
  onChanged,
}: {
  team: Team | null;
  agents: AgentListItem[];
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { addToast } = useApp();
  const confirm = useConfirm();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [mode, setMode] = useState('manager');
  const [newMember, setNewMember] = useState('');
  const [notes, setNotes] = useState<TeamNote[]>([]);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!team) return;
    setName(team.display_name || team.name);
    setDescription(team.description || '');
    setMode(team.mode || 'manager');
    void api.teams.notes(team.id).then((res) => setNotes(res.notes || [])).catch(() => {});
  }, [team]);

  if (!open || !team) return null;

  const save = async () => {
    setBusy(true);
    const res = await api.teams.update(team.id, {
      display_name: name.trim() || team.name,
      description: description.trim(),
      mode: mode as Team['mode'],
    });
    setBusy(false);
    if (res.error) addToast(res.error, { tone: 'error' });
    else {
      onChanged();
      addToast('Team updated', { tone: 'success' });
    }
  };

  const addMember = async () => {
    if (!newMember) return;
    const res = await api.teams.addMember(team.id, newMember);
    if (res.error) addToast(res.error, { tone: 'error' });
    else {
      setNewMember('');
      onChanged();
    }
  };

  const removeMember = async (agentId: string) => {
    const res = await api.teams.removeMember(team.id, agentId);
    if (res.error) addToast(res.error, { tone: 'error' });
    else onChanged();
  };

  const removeTeam = async () => {
    const ok = await confirm(`Delete team "${team.display_name || team.name}"?`, {
      title: 'Delete team',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    await api.teams.remove(team.id);
    onClose();
    onChanged();
    addToast('Team deleted', { tone: 'success' });
  };

  const addNote = async () => {
    if (!note.trim()) return;
    const res = await api.teams.addNote(team.id, note.trim());
    if (res.entry) setNotes((previous) => [...previous, res.entry as TeamNote]);
    setNote('');
  };

  const clearNotes = async () => {
    await api.teams.clearNotes(team.id);
    setNotes([]);
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Team settings"
      subtitle="Members, the manager and how the team runs."
      width={620}
      footer={
        <div className="ag-modal-foot">
          <Button size="sm" variant="secondary" onClick={() => void removeTeam()}>
            <Trash2 size={13} /> Delete team
          </Button>
          <span style={{ flex: 1 }} />
          <Button size="sm" onClick={onClose}>
            Close
          </Button>
          <Button size="sm" variant="primary" onClick={() => void save()} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </Button>
        </div>
      }
    >
      <div className="ag-modal-form">
        <Field label="Name">
          <TextInput value={name} onChange={(event) => setName(event.target.value)} />
        </Field>
        <Field label="Description">
          <TextArea rows={2} value={description} onChange={(event) => setDescription(event.target.value)} />
        </Field>
        <Field label="Mode">
          <Select value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="manager">Manager-led</option>
            <option value="roundtable">Roundtable</option>
            <option value="chain">Chain</option>
          </Select>
        </Field>
        <div className="ag-modal-members">
          <span>Shared notes</span>
          <div className="ag-modal-notes">
            {notes.length === 0 ? (
              <p className="ag-modal-empty">No notes yet.</p>
            ) : (
              notes.slice(-8).map((entry) => (
                <div key={entry.id} className="ag-modal-note">
                  <span>{entry.content}</span>
                  <em>{entry.label || entry.author}</em>
                </div>
              ))
            )}
          </div>
          <div className="ag-modal-inline">
            <TextInput
              value={note}
              onChange={(event) => setNote(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  void addNote();
                }
              }}
              placeholder="Add a note for the team"
            />
            <Button size="sm" variant="secondary" onClick={() => void addNote()} disabled={!note.trim()}>
              <Plus size={13} /> Add
            </Button>
            {notes.length > 0 && (
              <Button size="sm" variant="ghost" onClick={() => void clearNotes()}>
                Clear
              </Button>
            )}
          </div>
        </div>
        <div className="ag-modal-members">
          <span>Members</span>
          <div className="ag-modal-members__list">
            {team.members.map((member) => {
              const agent = member.agent || agents.find((item) => item.id === member.agent_id);
              return (
                <div key={member.agent_id} className="ag-modal-member">
                  <AgentAvatar
                    config={agent?.avatar_config}
                    upload={agent?.avatar_upload}
                    type={agent?.avatar_type === 'upload' ? 'upload' : 'bot'}
                    size={22}
                  />
                  <span>{agent?.display_name || agent?.name || member.agent_id}</span>
                  {member.agent_id === team.manager_agent_id && <em>manager</em>}
                  <button
                    type="button"
                    className="ag-icon-btn"
                    onClick={() => void removeMember(member.agent_id)}
                    aria-label={`Remove ${agent?.name || member.agent_id}`}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              );
            })}
            {team.members.length === 0 && <p className="ag-modal-empty">No members yet.</p>}
          </div>
          <div className="ag-modal-inline">
            <Select value={newMember} onChange={(event) => setNewMember(event.target.value)}>
              <option value="">Add an agent…</option>
              {agents
                .filter((agent) => !team.members.some((member) => member.agent_id === agent.id))
                .map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.display_name || agent.name}
                  </option>
                ))}
            </Select>
            <Button size="sm" variant="secondary" onClick={() => void addMember()} disabled={!newMember}>
              <Users size={13} /> Add
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
