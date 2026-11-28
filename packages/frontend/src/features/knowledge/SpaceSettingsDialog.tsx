import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Save, Trash2 } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { Dialog, SkeletonList } from '../../ui/primitives';

interface Profile {
  id: string;
  name: string;
  domain: string;
  headers: Record<string, string>;
  cookies: string;
  user_agent: string;
}

interface Props {
  open: boolean;
  spaceId: string | null;
  onClose: () => void;
  onChanged?: () => void;
}

export default function SpaceSettingsDialog({ open, spaceId, onClose, onChanged }: Props) {
  const { addToast } = useApp();
  const [mode, setMode] = useState<'off' | 'allow' | 'deny'>('off');
  const [domains, setDomains] = useState('');
  const [quotaMb, setQuotaMb] = useState('0');
  const [digestEnabled, setDigestEnabled] = useState(false);
  const [autoSaveResearch, setAutoSaveResearch] = useState(false);
  const [respectRobots, setRespectRobots] = useState(true);
  const [retentionDays, setRetentionDays] = useState('0');
  const [usage, setUsage] = useState<{ total_bytes: number; quota_bytes: number; percent: number | null } | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [digest, setDigest] = useState<{ title: string; text: string } | null>(null);

  const [profileName, setProfileName] = useState('');
  const [profileDomain, setProfileDomain] = useState('');
  const [profileHeaders, setProfileHeaders] = useState('');
  const [profileCookies, setProfileCookies] = useState('');
  const [profileAgent, setProfileAgent] = useState('');

  const load = useCallback(async () => {
    if (!spaceId) return;
    setLoading(true);
    try {
      const [policy, listed, usageData] = await Promise.all([
        api.spaces.policy.get(spaceId),
        api.spaces.profiles.list(spaceId),
        api.spaces.usage(spaceId),
      ]);
      if (!policy.error) {
        setMode(policy.domain_mode || 'off');
        setDomains((policy.domains || []).join('\n'));
        setQuotaMb(policy.quota_bytes ? String(Math.round(policy.quota_bytes / (1024 * 1024))) : '0');
        setDigestEnabled(Boolean(policy.digest_enabled));
        setAutoSaveResearch(Boolean(policy.auto_save_research));
        setRespectRobots(policy.respect_robots !== false);
        setRetentionDays(String(policy.retention_days || 0));
      }
      setProfiles(listed.profiles || []);
      if (!usageData.error) setUsage(usageData);
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not load space settings.', { tone: 'error' });
    } finally {
      setLoading(false);
    }
  }, [spaceId, addToast]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const savePolicy = async () => {
    if (!spaceId) return;
    setSaving(true);
    try {
      const data = await api.spaces.policy.update(spaceId, {
        domain_mode: mode,
        domains: domains
          .split(/[\n,]+/)
          .map((item) => item.trim())
          .filter(Boolean),
        quota_bytes: Math.max(0, Number(quotaMb) || 0) * 1024 * 1024,
        digest_enabled: digestEnabled,
        auto_save_research: autoSaveResearch,
        respect_robots: respectRobots,
        retention_days: Math.max(0, Number(retentionDays) || 0),
      });
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      addToast('Space settings saved', { tone: 'success' });
      onChanged?.();
      await load();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not save settings.', { tone: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const saveProfile = async () => {
    if (!spaceId || !profileDomain.trim()) return;
    try {
      const data = await api.spaces.profiles.save(spaceId, {
        name: profileName.trim() || profileDomain.trim(),
        domain: profileDomain.trim(),
        headers: profileHeaders,
        cookies: profileCookies,
        user_agent: profileAgent,
      });
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      addToast('Capture profile saved', { tone: 'success' });
      setProfileName('');
      setProfileDomain('');
      setProfileHeaders('');
      setProfileCookies('');
      setProfileAgent('');
      await load();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not save the profile.', { tone: 'error' });
    }
  };

  const removeProfile = async (id: string) => {
    if (!spaceId) return;
    try {
      await api.spaces.profiles.remove(spaceId, id);
      await load();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not remove the profile.', { tone: 'error' });
    }
  };

  const previewDigest = async () => {
    if (!spaceId) return;
    try {
      const data = await api.spaces.digest.preview(spaceId, 1);
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      setDigest({ title: data.title, text: data.text });
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not build the digest.', { tone: 'error' });
    }
  };

  const createDigest = async () => {
    if (!spaceId) return;
    try {
      const data = await api.spaces.digest.create(spaceId, 1, true);
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      addToast('Digest saved as a source', { tone: 'success' });
      onChanged?.();
      await load();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not save the digest.', { tone: 'error' });
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Space settings"
      subtitle="Domain policy, storage quota, capture profiles and digest."
      width={760}
      footer={
        <>
          <button type="button" className="ui-btn" onClick={onClose}>
            Close
          </button>
          <button type="button" className="ui-btn ui-btn--primary" disabled={saving} onClick={() => void savePolicy()}>
            <Save size={13} /> {saving ? 'Saving…' : 'Save policy'}
          </button>
        </>
      }
    >
      {loading ? (
        <SkeletonList rows={6} avatar={false} />
      ) : (
        <div className="space-settings">
          <section className="space-settings__section">
            <h4>Domain policy</h4>
            <div className="space-settings__row">
              <select className="ui-select" value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
                <option value="off">No restriction</option>
                <option value="allow">Only allow these domains</option>
                <option value="deny">Block these domains</option>
              </select>
              <span className="knowledge-muted">Subdomains are included.</span>
            </div>
            <textarea
              className="ui-input"
              rows={3}
              value={domains}
              disabled={mode === 'off'}
              placeholder={'example.com\nnews.ycombinator.com'}
              onChange={(e) => setDomains(e.target.value)}
            />
          </section>

          <section className="space-settings__section">
            <h4>Storage &amp; digest</h4>
            <div className="space-settings__row">
              <label className="space-settings__label">
                Quota (MB, 0 = unlimited)
                <input
                  className="ui-input"
                  type="number"
                  min={0}
                  value={quotaMb}
                  onChange={(e) => setQuotaMb(e.target.value)}
                />
              </label>
              <label className="space-settings__check">
                <input
                  type="checkbox"
                  checked={digestEnabled}
                  onChange={(e) => setDigestEnabled(e.target.checked)}
                />
                Generate a daily digest
              </label>
              <label className="space-settings__check">
                <input
                  type="checkbox"
                  checked={autoSaveResearch}
                  onChange={(e) => setAutoSaveResearch(e.target.checked)}
                />
                Save deep-research sources automatically
              </label>
              <label className="space-settings__check">
                <input
                  type="checkbox"
                  checked={respectRobots}
                  onChange={(e) => setRespectRobots(e.target.checked)}
                />
                Respect robots.txt
              </label>
              <label className="space-settings__label">
                Retention (days, 0 = keep)
                <input
                  className="ui-input"
                  type="number"
                  min={0}
                  value={retentionDays}
                  onChange={(e) => setRetentionDays(e.target.value)}
                />
              </label>
              <button
                type="button"
                className="ui-btn ui-btn--sm"
                onClick={() => {
                  void api.spaces.retention
                    .prune(spaceId!, Number(retentionDays) || 0, true)
                    .then((data) => {
                      if (data.error) addToast(data.error, { tone: 'error' });
                      else addToast(`${data.would_remove ?? 0} source(s) would be pruned`, { tone: 'success' });
                    });
                }}
              >
                Preview prune
              </button>
            </div>
            {usage ? (
              <p className="knowledge-muted">
                Used {(usage.total_bytes / (1024 * 1024)).toFixed(2)} MB
                {usage.quota_bytes ? ` of ${(usage.quota_bytes / (1024 * 1024)).toFixed(0)} MB` : ''}
                {usage.percent != null ? ` (${usage.percent}%)` : ''}.
              </p>
            ) : null}
            <div className="space-settings__row">
              <button type="button" className="ui-btn ui-btn--sm" onClick={() => void previewDigest()}>
                Preview digest
              </button>
              <button type="button" className="ui-btn ui-btn--sm" onClick={() => void createDigest()}>
                Save digest now
              </button>
              <a className="ui-btn ui-btn--sm" href={api.spaces.backupUrl(spaceId!)} download>
                Download backup
              </a>
              <label className="ui-btn ui-btn--sm">
                Restore backup
                <input
                  type="file"
                  accept=".zip,application/zip"
                  hidden
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    const name = window.prompt('Name for the restored space', 'Restored space');
                    if (!name) return;
                    void api.spaces
                      .restore(file, name)
                      .then((data) => {
                        if (data.error) {
                          addToast(data.error, { tone: 'error' });
                          return;
                        }
                        addToast('Backup restored', { tone: 'success' });
                        window.dispatchEvent(new CustomEvent('palimind:spaces-changed'));
                        onChanged?.();
                      })
                      .catch((err) =>
                        addToast(err instanceof Error ? err.message : 'Restore failed.', {
                          tone: 'error',
                        }),
                      );
                    e.target.value = '';
                  }}
                />
              </label>
            </div>
            {digest ? (
              <pre className="source-reader__content space-settings__digest">{digest.text}</pre>
            ) : null}
          </section>

          <section className="space-settings__section">
            <h4>Capture profiles</h4>
            <p className="knowledge-muted">
              Headers, cookies or a user agent for matching domains. Stored locally.
            </p>
            {profiles.length ? (
              <ul className="space-settings__profiles">
                {profiles.map((profile) => (
                  <li key={profile.id}>
                    <span>
                      <strong>{profile.name}</strong> · {profile.domain}
                      {Object.keys(profile.headers).length ? ` · ${Object.keys(profile.headers).length} header(s)` : ''}
                      {profile.cookies ? ' · cookies' : ''}
                    </span>
                    <button
                      type="button"
                      className="ui-icon-btn"
                      title="Remove profile"
                      aria-label="Remove profile"
                      onClick={() => void removeProfile(profile.id)}
                    >
                      <Trash2 size={13} />
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="knowledge-muted">No profiles yet.</p>
            )}
            <div className="space-settings__grid">
              <input
                className="ui-input"
                placeholder="Name"
                value={profileName}
                onChange={(e) => setProfileName(e.target.value)}
              />
              <input
                className="ui-input"
                placeholder="example.com"
                value={profileDomain}
                onChange={(e) => setProfileDomain(e.target.value)}
              />
              <textarea
                className="ui-input"
                rows={3}
                placeholder={'Authorization: Bearer …\nX-API-Key: …'}
                value={profileHeaders}
                onChange={(e) => setProfileHeaders(e.target.value)}
              />
              <input
                className="ui-input"
                placeholder="session=abc; other=def"
                value={profileCookies}
                onChange={(e) => setProfileCookies(e.target.value)}
              />
              <input
                className="ui-input"
                placeholder="Custom user agent (optional)"
                value={profileAgent}
                onChange={(e) => setProfileAgent(e.target.value)}
              />
            </div>
            <button
              type="button"
              className="ui-btn ui-btn--sm"
              disabled={!profileDomain.trim()}
              onClick={() => void saveProfile()}
            >
              <RefreshCw size={12} /> Add profile
            </button>
          </section>
        </div>
      )}
    </Dialog>
  );
}
