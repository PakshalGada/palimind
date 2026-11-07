import { useCallback, useEffect, useState } from 'react';
import {
  BarChart3,
  Database,
  Globe2,
  Server,
  Trash2,
  X,
} from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { useConfirm } from '../../components/ConfirmDialog';
import { Button, Chip, TextInput } from '../../ui/primitives';
import type { AgentListItem } from '../../types';
import './SettingsDrawer.css';

type Section = 'providers' | 'usage' | 'browser' | 'data';

interface Aggregate {
  total?: { prompt_tokens?: number; completion_tokens?: number; cost_estimate?: number; calls?: number };
  by_provider?: { provider: string; prompt_tokens: number; completion_tokens: number; cost_estimate: number; calls: number }[];
  unpriced_calls?: number;
}

interface ProviderRow {
  id: string;
  available: boolean;
  capabilities?: Record<string, boolean | number>;
  error?: string;
}

interface ModelRow {
  id: string;
  provider: string;
  name?: string;
}

interface Profile {
  id: string;
  name: string;
  color?: string;
  partition?: string;
}

const SECTIONS: { id: Section; label: string; icon: typeof Server }[] = [
  { id: 'providers', label: 'Providers', icon: Server },
  { id: 'usage', label: 'Usage', icon: BarChart3 },
  { id: 'browser', label: 'Browser', icon: Globe2 },
  { id: 'data', label: 'Data', icon: Database },
];

export default function SettingsDrawer({
  open,
  agents,
  onClose,
}: {
  open: boolean;
  agents: AgentListItem[];
  onClose: () => void;
}) {
  const { addToast } = useApp();
  const confirm = useConfirm();
  const [section, setSection] = useState<Section>('providers');
  const [providers, setProviders] = useState<ProviderRow[]>([]);
  const [models, setModels] = useState<ModelRow[]>([]);
  const [usage, setUsage] = useState<Aggregate | null>(null);
  const [days, setDays] = useState(30);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [newProfile, setNewProfile] = useState('');
  const [error, setError] = useState<string | null>(null);

  const loadProviders = useCallback(async () => {
    try {
      const data = await api.providers.list();
      setProviders((data.providers || []) as unknown as ProviderRow[]);
      setModels((data.models || []) as unknown as ModelRow[]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load providers.');
    }
  }, []);

  const loadUsage = useCallback(async () => {
    const end = new Date();
    const start = new Date(end.getTime() - (days - 1) * 86400000);
    try {
      const data = await api.usage.get('', start.toISOString().slice(0, 10), end.toISOString().slice(0, 10));
      setUsage(data as unknown as Aggregate);
    } catch {
      setUsage(null);
    }
  }, [days]);

  const loadProfiles = useCallback(async () => {
    try {
      const data = await api.browser.profiles();
      setProfiles((data.profiles || []) as unknown as Profile[]);
    } catch {
      setProfiles([]);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void loadProviders();
    void loadProfiles();
  }, [open, loadProviders, loadProfiles]);

  useEffect(() => {
    if (!open || section !== 'usage') return;
    void loadUsage();
  }, [open, section, loadUsage]);

  const addProfile = async () => {
    if (!newProfile.trim()) return;
    const res = await api.browser.createProfile(newProfile.trim());
    if (res.error) addToast(res.error, { tone: 'error' });
    setNewProfile('');
    await loadProfiles();
  };

  const removeProfile = async (profile: Profile) => {
    if (profile.id === 'shared') return;
    const ok = await confirm(`Delete browser profile "${profile.name}"?`, {
      title: 'Delete profile',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    await api.browser.removeProfile(profile.id);
    await loadProfiles();
  };

  const clearChats = async () => {
    const ok = await confirm(
      `Clear conversations for ${agents.length} agent${agents.length === 1 ? '' : 's'}? Memory and settings are kept.`,
      { title: 'Clear conversations', confirmLabel: 'Clear', danger: true },
    );
    if (!ok) return;
    await Promise.all(agents.map((agent) => api.agents.clearSessions(agent.id).catch(() => null)));
    addToast('Conversations cleared', { tone: 'success' });
  };

  if (!open) return null;

  return (
    <div className="ag-settings" role="dialog" aria-modal="true" aria-label="Agents settings">
      <button type="button" className="ag-settings__scrim" onClick={onClose} aria-label="Close settings" />
      <aside className="ag-settings__panel">
        <header className="ag-settings__head">
          <h2>Agents settings</h2>
          <button type="button" className="ag-icon-btn" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </header>
        <nav className="ag-settings__rail" aria-label="Settings sections">
          {SECTIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={section === item.id ? 'is-on' : ''}
              onClick={() => setSection(item.id)}
            >
              <item.icon size={15} />
              {item.label}
            </button>
          ))}
        </nav>
        <div className="ag-settings__body">
          {section === 'providers' && (
            <section className="ag-settings__section">
              {error && <p className="ag-settings__error">{error}</p>}
              <div className="ag-settings__list">
                {providers.map((provider) => (
                  <div key={provider.id} className="ag-settings__row">
                    <div>
                      <strong>{provider.id}</strong>
                      <span>
                        {provider.available
                          ? 'available'
                          : provider.error || 'unavailable'}
                      </span>
                    </div>
                    <Chip tone={provider.available ? 'muted' : 'danger'}>
                      {provider.available ? 'ready' : 'offline'}
                    </Chip>
                  </div>
                ))}
                {providers.length === 0 && <p className="ag-settings__empty">No providers configured.</p>}
              </div>
              <h3>Models</h3>
              <div className="ag-settings__models">
                {models.slice(0, 40).map((model) => (
                  <div key={`${model.provider}:${model.id}`} className="ag-settings__model">
                    <span>{model.name || model.id}</span>
                    <em>{model.provider}</em>
                  </div>
                ))}
              </div>
            </section>
          )}

          {section === 'usage' && (
            <section className="ag-settings__section">
              <div className="ag-settings__section-head">
                <h3>Local usage</h3>
                <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
                  <option value={7}>7 days</option>
                  <option value={30}>30 days</option>
                  <option value={90}>90 days</option>
                </select>
              </div>
              <div className="ag-settings__stats">
                <div><span>Calls</span><strong>{usage?.total?.calls ?? 0}</strong></div>
                <div><span>Prompt</span><strong>{usage?.total?.prompt_tokens ?? 0}</strong></div>
                <div><span>Completion</span><strong>{usage?.total?.completion_tokens ?? 0}</strong></div>
                <div><span>Cost</span><strong>${(usage?.total?.cost_estimate ?? 0).toFixed(4)}</strong></div>
              </div>
              <h3>By provider</h3>
              <div className="ag-settings__table">
                {(usage?.by_provider || []).map((row) => (
                  <div key={row.provider} className="ag-settings__tr">
                    <span>{row.provider || 'unknown'}</span>
                    <span>{row.calls}</span>
                    <span>{row.prompt_tokens + row.completion_tokens}</span>
                    <span>${row.cost_estimate.toFixed(4)}</span>
                  </div>
                ))}
                {(usage?.by_provider || []).length === 0 && (
                  <p className="ag-settings__empty">No usage recorded in this range.</p>
                )}
              </div>
            </section>
          )}

          {section === 'browser' && (
            <section className="ag-settings__section">
              <h3>Profiles</h3>
              <p className="ag-settings__note">
                Profiles keep cookies and sign-ins separate. Agents never see credentials.
              </p>
              <div className="ag-settings__list">
                {profiles.map((profile) => (
                  <div key={profile.id} className="ag-settings__row">
                    <div>
                      <strong>{profile.name}</strong>
                      <span>{profile.id === 'shared' ? 'default profile' : profile.partition || profile.id}</span>
                    </div>
                    {profile.id !== 'shared' && (
                      <button
                        type="button"
                        className="ag-icon-btn"
                        onClick={() => void removeProfile(profile)}
                        aria-label={`Delete ${profile.name}`}
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
              <div className="ag-settings__inline">
                <TextInput
                  value={newProfile}
                  onChange={(event) => setNewProfile(event.target.value)}
                  placeholder="New profile name"
                />
                <Button size="sm" variant="secondary" onClick={() => void addProfile()}>
                  Add
                </Button>
              </div>
            </section>
          )}

          {section === 'data' && (
            <section className="ag-settings__section">
              <h3>Conversations</h3>
              <p className="ag-settings__note">
                Clearing conversations keeps each agent's memory, settings and run history.
              </p>
              <Button variant="secondary" size="sm" onClick={() => void clearChats()}>
                Clear all agent conversations
              </Button>
            </section>
          )}
        </div>
      </aside>
    </div>
  );
}
