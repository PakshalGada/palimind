import { useCallback, useEffect, useState } from 'react';
import { Check, Globe2, Inbox as InboxIcon, ShieldAlert, X } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import { Button, Chip, EmptyState } from '../../ui/primitives';
import type { AgentListItem, Approval, BrowserTakeover } from '../../types';
import './AgentsInbox.css';

export default function AgentsInbox({ open, onClose }: { open: boolean; onClose: () => void }) {
  const {
    refreshOverview,
    addToast,
    setBrowserOpen,
    setBrowserFullscreen,
    setAgentsView,
    setSelectedAgentId,
    setSelectedTeamId,
    setSelectedChannelId,
  } = useApp();
  const [items, setItems] = useState<Approval[]>([]);
  const [takeovers, setTakeovers] = useState<BrowserTakeover[]>([]);
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [data, browser, roster] = await Promise.all([
        api.agents.inbox(),
        api.browser.takeovers('', 'pending'),
        api.agents.list(),
      ]);
      setItems(data.approvals || []);
      setTakeovers((browser.takeovers || []) as unknown as BrowserTakeover[]);
      setAgents(roster.agents || []);
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

  const takeOver = async (takeover: BrowserTakeover) => {
    await api.browser.acceptTakeover(takeover.id);
    setTakeovers((previous) => previous.filter((item) => item.id !== takeover.id));
    setSelectedTeamId(null);
    setSelectedChannelId(null);
    setSelectedAgentId(takeover.agent_id);
    setAgentsView('chat');
    setBrowserOpen(true);
    setBrowserFullscreen(false);
    onClose();
    window.dispatchEvent(new CustomEvent('palimind:browser-takeover'));
  };

  const total = items.length + takeovers.length;

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
              <h2>Inbox</h2>
              <p>{total === 0 ? 'Nothing waiting on you.' : `${total} action${total === 1 ? '' : 's'} waiting`}</p>
            </div>
          </div>
          <button type="button" className="inbox__close" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </header>

        <div className="inbox__body">
          {takeovers.length > 0 && (
            <>
              <div className="inbox__group">Browser handoffs</div>
              {takeovers.map((takeover) => (
                <article key={takeover.id} className="inbox__item">
                  <div className="inbox__item-head">
                    <span className="inbox__icon"><Globe2 size={16} /></span>
                    <div className="inbox__item-id">
                      <span className="inbox__item-name">
                        {agents.find((agent) => agent.id === takeover.agent_id)?.display_name ||
                          agents.find((agent) => agent.id === takeover.agent_id)?.name ||
                          takeover.agent_id}
                      </span>
                      <span className="inbox__item-tool">browser</span>
                    </div>
                    <Chip tone="warn"><Globe2 size={11} /> browser</Chip>
                  </div>
                  <p className="inbox__summary">{takeover.reason || 'The agent needs you to complete a step in the browser.'}</p>
                  <div className="inbox__actions">
                    <button
                      type="button"
                      className="inbox__always"
                      onClick={() => {
                        void api.browser.resolveTakeover(takeover.id, 'cancelled').then(() => {
                          setTakeovers((previous) => previous.filter((item) => item.id !== takeover.id));
                        });
                      }}
                    >
                      Dismiss request
                    </button>
                    <span className="inbox__spacer" />
                    <Button size="sm" variant="primary" onClick={() => void takeOver(takeover)}>
                      Take over
                    </Button>
                  </div>
                </article>
              ))}
            </>
          )}
          {items.length === 0 && takeovers.length === 0 ? (
            <EmptyState
              icon={<Check size={22} />}
              title="All clear"
              description="When an agent needs permission for a risky action, or needs you in the browser, it appears here."
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
