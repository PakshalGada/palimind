import { useState } from 'react';
import { Hash } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { Button, Field, Modal, TextArea, TextInput } from '../../ui/primitives';
import type { AgentListItem } from '../../types';

export default function NewChannelModal({
  open,
  agents,
  onClose,
  onCreated,
}: {
  open: boolean;
  agents: AgentListItem[];
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const { addToast } = useApp();
  const [name, setName] = useState('');
  const [purpose, setPurpose] = useState('');
  const [members, setMembers] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    if (!name.trim()) {
      addToast('Give the channel a name.', { tone: 'error' });
      return;
    }
    setBusy(true);
    try {
      const res = await api.channels.create({
        name: name.trim(),
        purpose: purpose.trim(),
        members,
      });
      const channel = res.channel as { id?: string } | undefined;
      if (res.error || !channel?.id) throw new Error(res.error || 'Could not create channel');
      setName('');
      setPurpose('');
      setMembers([]);
      onCreated(channel.id);
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not create channel', { tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New channel"
      subtitle="A shared room where a few agents work in one thread."
      width={560}
      footer={
        <div className="ag-modal-foot">
          <Button size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" variant="primary" onClick={() => void create()} disabled={busy}>
            <Hash size={13} /> {busy ? 'Creating…' : 'Create channel'}
          </Button>
        </div>
      }
    >
      <div className="ag-modal-form">
        <Field label="Name">
          <TextInput value={name} onChange={(event) => setName(event.target.value)} placeholder="launch" />
        </Field>
        <Field label="Purpose" hint="Optional. One sentence the agents can see.">
          <TextArea
            rows={2}
            value={purpose}
            onChange={(event) => setPurpose(event.target.value)}
            placeholder="Coordinate the release notes and launch checklist."
          />
        </Field>
        <div className="ag-modal-members">
          <span>Members</span>
          <div>
            {agents.map((agent) => (
              <label key={agent.id}>
                <input
                  type="checkbox"
                  checked={members.includes(agent.id)}
                  onChange={(event) =>
                    setMembers((previous) =>
                      event.target.checked
                        ? [...previous, agent.id]
                        : previous.filter((id) => id !== agent.id),
                    )
                  }
                />
                {agent.display_name || agent.name}
              </label>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  );
}
