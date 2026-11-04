import { useCallback, useEffect, useState } from 'react';
import { Check, Inbox as InboxIcon, ShieldAlert, X } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import { Button, Chip, EmptyState } from '../../ui/primitives';
import type { Approval } from '../../types';
import './AgentsInbox.css';

export default function AgentsInbox({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { refreshOverview, addToast } = useApp();
  const [items, setItems] = useState<Approval[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.agents.inbox();
      setItems(data.approvals || []);
    } catch {
      // best effort
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    const onChanged = () => void refresh();
    window.addEventListener('palimind:agents-changed', onChanged);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('palimind:agents-changed', onChanged);
    };
  }, [open, refresh]);

  const resolve = async (item: Approval, approved: boolean, alwaysAllow = false) => {
    await api.agents.approve(item.agent_id, approved, '', item.run_id);
    if (approved && alwaysAllow) {
      await api.agents.alwaysAllow(item.agent_id, item.tool);
    }
    setItems((prev) => prev.filter((x) => !(x.agent_id === item.agent_id && x.run_id === item.run_id)));
    void refreshOverview();
    window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    addToast(approved ? `Allowed ${item.tool}` : `Denied ${item.tool}`, {
      tone: approved ? 'success' : 'warning',
    });
  };

  if (!open) return null;

  return (
    <div className="inbox" role="dialog" aria-modal="true" aria-label="Approvals inbox">
      <button type="button" className="inbox__scrim" onClick={onClose} aria-label="Close inbox" />
      <aside className="inbox__panel">
        <header className="inbox__head">
          <div className="inbox__title">
            <span className="inbox__icon">
              <InboxIcon size={16} />
            </span>
            <div>
              <h2>Approvals</h2>
              <p>{items.length === 0 ? 'Nothing waiting on you.' : `${items.length} action${items.length === 1 ? '' : 's'} waiting`}</p>
            </div>
          </div>
          <button type="button" className="inbox__close" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </header>

        <div className="inbox__body">
          {items.length === 0 ? (
            <EmptyState
              icon={<Check size={22} />}
              title="All clear"
              description="When an agent needs permission for a risky action it appears here."
            />
          ) : (
            items.map((item) => {
              const key = `${item.agent_id}:${item.run_id}`;
              const isOpen = expanded === key;
              return (
                <article key={key} className="inbox__item">
                  <div className="inbox__item-head">
                    <AgentAvatar
                      config={item.agent_avatar?.config}
                      upload={item.agent_avatar?.upload}
                      type={item.agent_avatar?.type === 'upload' ? 'upload' : 'bot'}
                      size={32}
                    />
                    <div className="inbox__item-id">
                      <span className="inbox__item-name">{item.agent_label || item.agent_name || item.agent_id}</span>
                      <span className="inbox__item-tool">
                        {item.tool}
                        {item.tier ? ` · tier ${item.tier}` : ''}
                      </span>
                    </div>
                    <Chip tone="warn">
                      <ShieldAlert size={11} /> review
                    </Chip>
                  </div>
                  <p className="inbox__summary">{item.summary || item.reasoning || 'This action needs your approval.'}</p>
                  {isOpen && (
                    <pre className="inbox__args">{JSON.stringify(item.args, null, 2)}</pre>
                  )}
                  <div className="inbox__actions">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setExpanded(isOpen ? null : key)}
                    >
                      {isOpen ? 'Hide details' : 'Details'}
                    </Button>
                    <span className="inbox__spacer" />
                    <Button size="sm" variant="secondary" onClick={() => void resolve(item, false)}>
                      Deny
                    </Button>
                    <Button size="sm" variant="primary" onClick={() => void resolve(item, true)}>
                      Approve
                    </Button>
                  </div>
                  <button
                    type="button"
                    className="inbox__always"
                    onClick={() => void resolve(item, true, true)}
                  >
                    Always allow <strong>{item.tool}</strong> for this agent
                  </button>
                </article>
              );
            })
          )}
        </div>
      </aside>
    </div>
  );
}
