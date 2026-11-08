import { useCallback, useEffect, useState } from 'react';
import {
  BarChart3,
  Database,
  Globe2,
  Plug,
  Server,
  Trash2,
  Wrench,
  X,
} from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { useConfirm } from '../../components/ConfirmDialog';
import { Button, Chip, TextInput } from '../../ui/primitives';
import type { AgentListItem, MarketplaceSkill, SkillMeta } from '../../types';
import './SettingsDrawer.css';

type Section = 'providers' | 'usage' | 'browser' | 'skills' | 'mcp' | 'plugins' | 'data';

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
  { id: 'skills', label: 'Skills', icon: Wrench },
  { id: 'mcp', label: 'MCP', icon: Plug },
  { id: 'plugins', label: 'Plugins', icon: Plug },
  { id: 'data', label: 'Data', icon: Database },
];

interface McpServer {
  name?: string;
  status?: string;
  tools?: number;
  error?: string;
  command?: string;
}

interface PluginRow {
  id: string;
  name?: string;
  description?: string;
  installed?: boolean;
}

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
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [marketSkills, setMarketSkills] = useState<MarketplaceSkill[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [plugins, setPlugins] = useState<PluginRow[]>([]);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [sections, setSections] = useState<{ id: string; name: string }[]>([]);
  const [newSection, setNewSection] = useState('');

  const loadSections = useCallback(async () => {
    try {
      const data = await api.agents.sections.list();
      setSections(data.sections || []);
    } catch {
      setSections([]);
    }
  }, []);

  const addSection = async () => {
    const name = newSection.trim();
    if (!name) return;
    await api.agents.sections.create(name);
    setNewSection('');
    await loadSections();
    window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
  };

  const removeSection = async (sectionId: string) => {
    await api.agents.sections.remove(sectionId);
    await loadSections();
    window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
  };

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

  const loadSkills = useCallback(async () => {
    try {
      const [installed, market] = await Promise.all([
        api.agents.skills(),
        api.agents.skillsAdmin.marketplace().catch(() => ({ skills: [] as MarketplaceSkill[] })),
      ]);
      setSkills(installed.skills || []);
      setMarketSkills(market.skills || []);
    } catch {
      setSkills([]);
    }
  }, []);

  const loadMcp = useCallback(async () => {
    try {
      const data = await api.mcp.servers();
      setMcpServers((data.servers || []) as unknown as McpServer[]);
    } catch {
      setMcpServers([]);
    }
  }, []);

  const loadPlugins = useCallback(async () => {
    try {
      const data = await api.plugins.list();
      setPlugins((data.plugins || []) as unknown as PluginRow[]);
    } catch {
      setPlugins([]);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void loadProviders();
    void loadProfiles();
    void loadSections();
  }, [open, loadProviders, loadProfiles, loadSections]);

  useEffect(() => {
    if (!open) return;
    if (section === 'skills') void loadSkills();
    if (section === 'mcp') void loadMcp();
    if (section === 'plugins') void loadPlugins();
  }, [open, section, loadSkills, loadMcp, loadPlugins]);

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

  const installSkill = async (skill: MarketplaceSkill) => {
    setBusyKey(`skill:${skill.id}`);
    try {
      const res = await api.agents.skillsAdmin.marketplaceInstall(skill.id);
      if (res.error) addToast(res.error, { tone: 'error' });
      else addToast(`Installed ${skill.name || skill.id}`, { tone: 'success' });
      await loadSkills();
    } finally {
      setBusyKey(null);
    }
  };

  const uninstallSkill = async (skill: SkillMeta) => {
    setBusyKey(`skill:${skill.id}`);
    try {
      await api.agents.skillsAdmin.uninstall(skill.id);
      await loadSkills();
    } finally {
      setBusyKey(null);
    }
  };

  const reloadMcp = async () => {
    setBusyKey('mcp');
    try {
      const res = await api.mcp.reload();
      if (res.error) addToast(res.error, { tone: 'error' });
      else addToast('MCP servers reloaded', { tone: 'success' });
      await loadMcp();
    } finally {
      setBusyKey(null);
    }
  };

  const installPlugin = async (plugin: PluginRow) => {
    setBusyKey(`plugin:${plugin.id}`);
    try {
      const res = await api.plugins.install(plugin.id);
      if (res.error) addToast(res.error, { tone: 'error' });
      else addToast(`Installed ${plugin.name || plugin.id}`, { tone: 'success' });
      await loadPlugins();
    } finally {
      setBusyKey(null);
    }
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

          {section === 'skills' && (
            <section className="ag-settings__section">
              <div className="ag-settings__section-head">
                <h3>Installed skills</h3>
                <span>{skills.length}</span>
              </div>
              <p className="ag-settings__note">
                Skills add focused instructions and tools to an agent. Attach them per agent in its settings.
              </p>
              <div className="ag-settings__list">
                {skills.map((skill) => (
                  <div key={skill.id} className="ag-settings__row">
                    <div>
                      <strong>{skill.name || skill.id}</strong>
                      <span>{skill.description || skill.category}</span>
                    </div>
                    {skill.builtin ? (
                      <Chip tone="muted">built-in</Chip>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busyKey === `skill:${skill.id}`}
                        onClick={() => void uninstallSkill(skill)}
                      >
                        Remove
                      </Button>
                    )}
                  </div>
                ))}
                {skills.length === 0 && <p className="ag-settings__empty">No skills installed.</p>}
              </div>
              <h3>Marketplace</h3>
              <div className="ag-settings__list">
                {marketSkills.map((skill) => (
                  <div key={skill.id} className="ag-settings__row">
                    <div>
                      <strong>{skill.name || skill.id}</strong>
                      <span>{skill.description || skill.category}</span>
                    </div>
                    <Button
                      size="sm"
                      variant={skill.installed ? 'ghost' : 'secondary'}
                      disabled={busyKey === `skill:${skill.id}`}
                      onClick={() => void installSkill(skill)}
                    >
                      {skill.installed ? 'Reinstall' : 'Install'}
                    </Button>
                  </div>
                ))}
                {marketSkills.length === 0 && <p className="ag-settings__empty">No marketplace entries.</p>}
              </div>
            </section>
          )}

          {section === 'mcp' && (
            <section className="ag-settings__section">
              <div className="ag-settings__section-head">
                <h3>MCP servers</h3>
                <Button size="sm" variant="secondary" disabled={busyKey === 'mcp'} onClick={() => void reloadMcp()}>
                  Reload
                </Button>
              </div>
              <p className="ag-settings__note">
                Model Context Protocol servers add external tools. Reload after editing the local config.
              </p>
              <div className="ag-settings__list">
                {mcpServers.map((server, index) => (
                  <div key={`${server.name || index}`} className="ag-settings__row">
                    <div>
                      <strong>{server.name || `Server ${index + 1}`}</strong>
                      <span>{server.error || server.command || server.status || 'ready'}</span>
                    </div>
                    <Chip tone={server.error ? 'danger' : 'muted'}>
                      {server.error ? 'error' : `${server.tools ?? 0} tools`}
                    </Chip>
                  </div>
                ))}
                {mcpServers.length === 0 && <p className="ag-settings__empty">No MCP servers configured.</p>}
              </div>
            </section>
          )}

          {section === 'plugins' && (
            <section className="ag-settings__section">
              <h3>Plugins</h3>
              <p className="ag-settings__note">
                Plugins bundle connector tools that agents can opt into.
              </p>
              <div className="ag-settings__list">
                {plugins.map((plugin) => (
                  <div key={plugin.id} className="ag-settings__row">
                    <div>
                      <strong>{plugin.name || plugin.id}</strong>
                      <span>{plugin.description || plugin.id}</span>
                    </div>
                    <Button
                      size="sm"
                      variant={plugin.installed ? 'ghost' : 'secondary'}
                      disabled={busyKey === `plugin:${plugin.id}`}
                      onClick={() => void installPlugin(plugin)}
                    >
                      {plugin.installed ? 'Reinstall' : 'Install'}
                    </Button>
                  </div>
                ))}
                {plugins.length === 0 && <p className="ag-settings__empty">No plugins available.</p>}
              </div>
            </section>
          )}

          {section === 'data' && (
            <section className="ag-settings__section">
              <h3>Sections</h3>
              <p className="ag-settings__note">
                Group agents in the rail. Right-click an agent to move it into a section.
              </p>
              <div className="ag-settings__list">
                {sections.map((item) => (
                  <div key={item.id} className="ag-settings__row">
                    <div>
                      <strong>{item.name}</strong>
                    </div>
                    <button
                      type="button"
                      className="ag-icon-btn"
                      aria-label={`Delete ${item.name}`}
                      onClick={() => void removeSection(item.id)}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
                {sections.length === 0 && <p className="ag-settings__empty">No sections yet.</p>}
              </div>
              <div className="ag-settings__inline">
                <TextInput
                  value={newSection}
                  onChange={(event) => setNewSection(event.target.value)}
                  placeholder="New section name"
                />
                <Button size="sm" variant="secondary" onClick={() => void addSection()}>
                  Add
                </Button>
              </div>
              <h3>Conversations</h3>
              <p className="ag-settings__note">
                Clearing conversations keeps each agent's memory, settings and run history.
              </p>
              <Button variant="secondary" size="sm" onClick={() => void clearChats()}>
                Clear all agent conversations
              </Button>
              <h3>Notifications</h3>
              <p className="ag-settings__note">
                Get a desktop notification when an agent stops to ask a question or waits for approval.
              </p>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  if (typeof Notification === 'undefined') {
                    addToast('Notifications are not available here.', { tone: 'warning' });
                    return;
                  }
                  void Notification.requestPermission().then((permission) => {
                    addToast(
                      permission === 'granted'
                        ? 'Notifications enabled'
                        : 'Notifications were not enabled',
                      { tone: permission === 'granted' ? 'success' : 'warning' },
                    );
                  });
                }}
              >
                Enable notifications
              </Button>
            </section>
          )}
        </div>
      </aside>
    </div>
  );
}
