import { useCallback, useEffect, useState } from 'react';
import { Copy, Download, Plus, Trash2 } from 'lucide-react';
import { api } from '../api';
import { useApp } from '../AppContext';
import { Badge, Button, Chip, EmptyState, Modal, Tabs, TextArea } from '../ui/primitives';
import type { MarketplaceSkill, SkillCommand, SkillMeta } from '../types';
import './SkillManager.css';

type Tab = 'installed' | 'marketplace' | 'commands';

const BLANK_SKILL = `{
  "id": "my-skill",
  "name": "My skill",
  "description": "One line describing what this skill does.",
  "category": "custom",
  "command": "/myskill",
  "tools": [],
  "instructions": "Always ..."
}`;

/**
 * Skill manager (Phase 4.3): browse, create, validate, install, uninstall and
 * share skills, plus the slash commands they expose. Open with the
 * `palimind:open-skill-manager` event.
 */
export default function SkillManager() {
  const { addToast } = useApp();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>('installed');
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [market, setMarket] = useState<MarketplaceSkill[]>([]);
  const [commands, setCommands] = useState<SkillCommand[]>([]);
  const [editor, setEditor] = useState('');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [s, m, c] = await Promise.all([
        api.agents.skills(),
        api.agents.skillsAdmin.marketplace(),
        api.agents.skillsAdmin.commands(),
      ]);
      setSkills(s.skills || []);
      setMarket(m.skills || []);
      setCommands(c.commands || []);
    } catch {
      // best effort
    }
  }, []);

  useEffect(() => {
    const onOpen = () => {
      setOpen(true);
      void refresh();
    };
    window.addEventListener('palimind:open-skill-manager', onOpen);
    return () => window.removeEventListener('palimind:open-skill-manager', onOpen);
  }, [refresh]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const edit = (skill: SkillMeta) => {
    const rest: Record<string, unknown> = { ...skill };
    delete rest.builtin;
    delete rest.source;
    setEditor(JSON.stringify(rest, null, 2));
    setEditing(true);
    setTab('installed');
  };

  const save = async () => {
    let parsed: SkillMeta;
    try {
      parsed = JSON.parse(editor);
    } catch {
      addToast('Skill is not valid JSON.');
      return;
    }
    setBusy(true);
    try {
      const validation = await api.agents.skillsAdmin.validate(parsed);
      if (!validation.valid) {
        addToast(validation.error || 'Invalid skill.');
        setBusy(false);
        return;
      }
      const res = await api.agents.skillsAdmin.install(parsed, true);
      if (res.error) addToast(res.error);
      else {
        addToast(`Saved skill '${parsed.id}'.`);
        setEditing(false);
        await refresh();
        window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
      }
    } catch (e) {
      addToast(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  };

  const remove = async (skill: SkillMeta) => {
    const res = await api.agents.skillsAdmin.uninstall(skill.id);
    if (res.status === 'success') {
      addToast(`Removed '${skill.id}'.`);
      await refresh();
    } else {
      addToast('Built-in skills cannot be removed.');
    }
  };

  const exportSkill = async (skill: SkillMeta) => {
    const res = await api.agents.skillsAdmin.export(skill.id);
    if (res.skill) {
      await navigator.clipboard.writeText(JSON.stringify(res.skill, null, 2)).catch(() => {});
      addToast('Skill JSON copied to clipboard.');
    }
  };

  const installMarket = async (id: string) => {
    const res = await api.agents.skillsAdmin.marketplaceInstall(id, true);
    if (res.error) addToast(res.error);
    else {
      addToast(`Installed '${id}'.`);
      await refresh();
    }
  };

  return (
    <Modal
      open={open}
      onClose={() => setOpen(false)}
      title="Skill manager"
      subtitle="Reusable behaviour bundles, slash commands and the marketplace"
      width={860}
    >
      <div className="sm">
        <Tabs<Tab>
          value={tab}
          onChange={setTab}
          tabs={[
            { id: 'installed', label: 'Installed', count: skills.length },
            { id: 'marketplace', label: 'Marketplace', count: market.length },
            { id: 'commands', label: 'Commands', count: commands.length },
          ]}
        />

        {tab === 'installed' && (
          <div className="sm-list">
            <div className="sm-toolbar">
              <Button
                size="sm"
                variant="primary"
                onClick={() => {
                  setEditor(BLANK_SKILL);
                  setEditing(true);
                }}
              >
                <Plus size={14} /> New skill
              </Button>
            </div>

            {editing && (
              <div className="sm-editor">
                <TextArea rows={12} value={editor} onChange={(e) => setEditor(e.target.value)} />
                <div className="sm-editor__actions">
                  <Button size="sm" onClick={() => setEditing(false)}>
                    Cancel
                  </Button>
                  <Button size="sm" variant="primary" disabled={busy} onClick={save}>
                    {busy ? 'Saving…' : 'Validate & save'}
                  </Button>
                </div>
              </div>
            )}

            {skills.length === 0 && <EmptyState title="No skills" description="Create one to get started." />}
            {skills.map((s) => (
              <div key={s.id} className="sm-row">
                <div className="sm-row__main">
                  <div className="sm-row__title">
                    <span>{s.name}</span>
                    {s.builtin && <Badge tone="muted">built-in</Badge>}
                    {s.command && <Chip tone="accent">{s.command}</Chip>}
                  </div>
                  <div className="sm-row__desc">{s.description}</div>
                  <div className="sm-row__meta">
                    <span>{s.category}</span>
                    {s.tools.length > 0 && <span>{s.tools.length} tools</span>}
                    {s.source && <span>{s.source}</span>}
                  </div>
                </div>
                <div className="sm-row__actions">
                  <Button size="sm" onClick={() => edit(s)}>
                    Edit
                  </Button>
                  <Button size="sm" title="Copy JSON" onClick={() => exportSkill(s)}>
                    <Copy size={13} />
                  </Button>
                  {!s.builtin && (
                    <Button size="sm" variant="danger" title="Uninstall" onClick={() => remove(s)}>
                      <Trash2 size={13} />
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === 'marketplace' && (
          <div className="sm-list">
            {market.map((s) => (
              <div key={s.id} className="sm-row">
                <div className="sm-row__main">
                  <div className="sm-row__title">
                    <span>{s.name}</span>
                    {s.version && <Badge tone="muted">v{s.version}</Badge>}
                    {s.command && <Chip tone="accent">{s.command}</Chip>}
                  </div>
                  <div className="sm-row__desc">{s.description}</div>
                  <div className="sm-row__meta">
                    <span>{s.author}</span>
                    <span>{s.tools.length} tools</span>
                  </div>
                </div>
                <div className="sm-row__actions">
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={s.installed}
                    onClick={() => installMarket(s.id)}
                  >
                    <Download size={13} /> {s.installed ? 'Installed' : 'Install'}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === 'commands' && (
          <div className="sm-list">
            {commands.length === 0 && <EmptyState title="No slash commands" />}
            {commands.map((c) => (
              <div key={c.command} className="sm-row">
                <div className="sm-row__main">
                  <div className="sm-row__title">
                    <Chip tone="accent">{c.command}</Chip>
                    <span>{c.name}</span>
                  </div>
                  <div className="sm-row__desc">{c.description}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}
