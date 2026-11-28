import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Search, X } from 'lucide-react';
import { useApp } from '../../AppContext';
import { api } from '../../api';
import type { Theme } from '../../types';
import { Button, SegmentedControl, Select, Toggle } from '../../ui/primitives';
import {
  applyMotion,
  applyPixelAccents,
  readMotion,
  readPixelAccents,
  type MotionSetting,
  type PixelAccents,
} from '../../design/usePixelMotion';
import { applyUiStyle, readUiStyle, type UiStyle } from '../../design/uiStyle';
import { getUserName, setUserName } from '../../utils/userName';
import {
  DEFAULT_TTS_VOICE,
  TTS_VOICES,
  getVoice,
  isAutoSpeakOn,
  setAutoSpeak,
  setVoice,
} from '../../utils/voicePrefs';
import {
  templateVariables,
  type PromptTemplate,
} from '../../utils/prompts';
import SettingsSelect from '../../components/SettingsSelect';
import '../../components/SettingsModal.css';
import './SettingsPage.css';

type SectionKey =
  | 'appearance'
  | 'voice'
  | 'prompts'
  | 'opencode'
  | 'models'
  | 'notifications'
  | 'desktop';

interface SectionDef {
  key: SectionKey;
  label: string;
  icon: ReactNode;
  keywords?: string[];
}

const SECTIONS: SectionDef[] = [
  {
    key: 'appearance',
    label: 'Appearance',
    keywords: ['theme', 'dark', 'light', 'name', 'motion', 'pixel', 'style'],
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 3a9 9 0 0 1 0 18V3z" fill="currentColor" stroke="none" opacity="0.55" />
      </svg>
    ),
  },
  {
    key: 'voice',
    label: 'Voice',
    keywords: ['speak', 'tts', 'speech', 'read aloud', 'whisper', 'stt', 'kokoro', 'audio'],
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M11 5 6 9H3v6h3l5 4V5z" />
        <path d="M15.5 8.5a5 5 0 0 1 0 7" />
        <path d="M18.5 5.5a9 9 0 0 1 0 13" />
      </svg>
    ),
  },
  {
    key: 'prompts',
    label: 'Prompt library',
    keywords: ['prompt', 'template', 'slash', 'command', 'variable', 'snippet'],
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="m13 2-2 8h5l-7 12 2-8H6l7-12z" />
      </svg>
    ),
  },
  {
    key: 'opencode',
    label: 'OpenCode',
    keywords: ['api key', 'cloud', 'connection'],
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="7.5" cy="15.5" r="3.5" />
        <path d="M10.2 12.8 20 3M15 8l2.5 2.5" />
      </svg>
    ),
  },
  {
    key: 'models',
    label: 'Models',
    keywords: ['embedding', 'index', 'whisper', 'transcribe'],
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
      </svg>
    ),
  },
  {
    key: 'notifications',
    label: 'Notifications',
    keywords: ['notify', 'desktop', 'permission', 'alert'],
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.7 21a2 2 0 0 1-3.4 0" />
      </svg>
    ),
  },
  {
    key: 'desktop',
    label: 'Computer use',
    keywords: ['desktop', 'accessibility', 'ghost cursor', 'agent', 'control'],
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="4" width="20" height="13" rx="2" />
        <path d="M8 21h8M12 17v4" />
        <path d="m9 9 2 2-2 2M13 13h3" />
      </svg>
    ),
  },
];

function SectionHeader({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="settings-section-header">
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

function Feedback({ message, isError }: { message: string; isError: boolean }) {
  if (!message) return null;
  return (
    <span className={`settings-feedback${isError ? ' error' : ''}`} role="status">
      {message}
    </span>
  );
}

interface DesktopStatusData {
  platform?: string;
  session_type?: string;
  permissions?: { accessibility?: { state?: string } };
  kernel_input?: { accessible?: boolean; detail?: string };
  screencast_token?: boolean;
  policy?: {
    enabled?: boolean;
    rate_limit_per_min?: number;
    stopped?: boolean;
  };
}

interface DesktopStatusView {
  ok: boolean;
  enabled: boolean;
  status?: DesktopStatusData;
  error?: unknown;
}

export default function SettingsPage() {
  const { theme, setTheme, addToast } = useApp();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const [section, setSection] = useState<SectionKey>('appearance');
  const [search, setSearch] = useState('');

  const [ocKeyConfigured, setOcKeyConfigured] = useState(false);
  const [ocKeyMasked, setOcKeyMasked] = useState<string | null>(null);
  const [ocKeyInput, setOcKeyInput] = useState('');
  const [ocKeyMsg, setOcKeyMsg] = useState('');
  const [ocKeyIsError, setOcKeyIsError] = useState(false);
  const [ocKeyBusy, setOcKeyBusy] = useState(false);
  const [showKey, setShowKey] = useState(false);

  const [sttModel, setSttModel] = useState('base.en');
  const [sttOptions, setSttOptions] = useState<
    { id: string; label: string; size_mb: number; note: string }[]
  >([]);
  const [sttMsg, setSttMsg] = useState('');
  const [sttError, setSttError] = useState(false);
  const [sttBusy, setSttBusy] = useState(false);

  const [embedModel, setEmbedModel] = useState('bge-m3');
  const [embedModelMsg, setEmbedModelMsg] = useState('');
  const [embedModelError, setEmbedModelError] = useState(false);
  const [embedModelBusy, setEmbedModelBusy] = useState(false);

  const [profileName, setProfileName] = useState(getUserName);
  const [pixelAccents, setPixelAccents] = useState<PixelAccents>(readPixelAccents);
  const [motion, setMotion] = useState<MotionSetting>(readMotion);
  const [uiStyle, setUiStyle] = useState<UiStyle>(readUiStyle);

  const [desktop, setDesktop] = useState<DesktopStatusView | null>(null);
  const [desktopBusy, setDesktopBusy] = useState(false);
  const [desktopMsg, setDesktopMsg] = useState('');
  const [desktopAudit, setDesktopAudit] = useState<Record<string, unknown>[]>([]);
  const [ghostCursor, setGhostCursor] = useState(
    () => typeof localStorage !== 'undefined' && localStorage.getItem('palimind:ghost-cursor') === '1',
  );

  const [voiceTick, setVoiceTick] = useState(0);
  const [permission, setPermission] = useState<string>(
    () => (typeof Notification !== 'undefined' ? Notification.permission : 'default'),
  );

  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [editingPrompt, setEditingPrompt] = useState<
    { id: string; name: string; command: string; description: string; template: string } | null
  >(null);
  const [promptMsg, setPromptMsg] = useState('');
  const [promptError, setPromptError] = useState(false);
  const [newPrompt, setNewPrompt] = useState({
    name: '',
    command: '',
    template: '',
    description: '',
  });

  useEffect(() => {
    if (!open) return;
    api.settings.opencodeKey.status().then((s) => {
      setOcKeyConfigured(s.configured);
      setOcKeyMasked(s.masked ?? null);
    }).catch(() => {});
    api.settings.voice.status().then((v) => {
      setSttModel(v.stt_whisper_model || 'base.en');
      setSttOptions(v.options || []);
    }).catch(() => {});
    api.config.get().then((cfg) => {
      if (cfg.embed_model) setEmbedModel(cfg.embed_model);
    }).catch(() => {});
    api.prompts
      .list()
      .then((data) => setPrompts(data.prompts || []))
      .catch(() => {});
    if (typeof Notification !== 'undefined') {
      setPermission(Notification.permission);
    }
  }, [open]);

  const close = useCallback(() => {
    setOpen(false);
    setShowKey(false);
  }, []);

  const refreshDesktop = useCallback(async () => {
    setDesktopBusy(true);
    try {
      const view = await api.desktop.status();
      setDesktop(view);
      setDesktopMsg('');
      const audit = await api.desktop.audit(6).catch(() => null);
      setDesktopAudit(audit?.data?.entries || []);
    } catch (error) {
      setDesktopMsg(String(error));
    } finally {
      setDesktopBusy(false);
    }
  }, []);

  useEffect(() => {
    if (open && section === 'desktop' && !desktop) void refreshDesktop();
  }, [open, section, desktop, refreshDesktop]);

  useEffect(() => {
    const openSettings = (event: Event) => {
      const requested = (event as CustomEvent<{ section?: SectionKey }>).detail?.section;
      if (requested && SECTIONS.some((item) => item.key === requested)) {
        setSection(requested);
      }
      setOpen(true);
    };
    window.addEventListener('palimind:open-settings', openSettings);
    return () => window.removeEventListener('palimind:open-settings', openSettings);
  }, []);

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    rootRef.current?.querySelector<HTMLElement>('.settings-page-search input')?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKey);
      restoreRef.current?.focus?.();
    };
  }, [open, close]);

  // Search: hide cards that don't match and sections with no matches. Plain
  // substring matching over each card's own text keeps the index automatic.
  const filteredNav = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return { nav: SECTIONS, empty: false };
    const nav = SECTIONS.filter((s) => {
      if (s.label.toLowerCase().includes(q)) return true;
      if ((s.keywords ?? []).some((k) => k.includes(q))) return true;
      const panel = rootRef.current?.querySelector(`#settings-panel-${s.key}`);
      return Boolean(
        panel && Array.from(panel.querySelectorAll('.settings-card')).some((card) =>
          card.textContent?.toLowerCase().includes(q),
        ),
      );
    });
    return { nav, empty: nav.length === 0 };
    // Re-run when the pane content changes (prompts list, audit entries).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, section, prompts, desktopAudit, ocKeyConfigured]);

  useEffect(() => {
    const pane = rootRef.current;
    if (!pane) return;
    const q = search.trim().toLowerCase();
    pane.querySelectorAll<HTMLElement>('.settings-section').forEach((panel) => {
      const key = panel.id.replace('settings-panel-', '');
      let matches = 0;
      panel.querySelectorAll<HTMLElement>('.settings-card').forEach((card) => {
        const hit = !q || Boolean(card.textContent?.toLowerCase().includes(q));
        card.style.display = hit ? '' : 'none';
        if (hit) matches += 1;
      });
      const header = panel.querySelector<HTMLElement>('.settings-section-header');
      const sectionVisible = !q || matches > 0 || filteredNav.nav.some((s) => s.key === key);
      panel.hidden = !(key === section || sectionVisible);
      if (header) header.style.display = q ? 'none' : '';
    });
  }, [search, section, filteredNav, open, prompts, desktopAudit]);

  const selectSection = (key: SectionKey) => {
    setSection(key);
    setOcKeyMsg('');
    setSttMsg('');
    setEmbedModelMsg('');
    setPromptMsg('');
  };

  const saveSttModel = async () => {
    setSttBusy(true);
    setSttMsg('');
    setSttError(false);
    try {
      const res = await api.settings.voice.save({ stt_whisper_model: sttModel });
      if (res.error) {
        setSttMsg(res.error);
        setSttError(true);
      } else {
        setSttMsg('Saved');
        setTimeout(() => setSttMsg(''), 2500);
      }
    } catch (e) {
      setSttMsg(e instanceof Error ? e.message : String(e));
      setSttError(true);
    }
    setSttBusy(false);
  };

  const saveEmbedModel = async () => {
    setEmbedModelBusy(true);
    setEmbedModelMsg('');
    setEmbedModelError(false);
    try {
      const res = await api.config.setEmbedModel(embedModel);
      if (res.error) {
        setEmbedModelMsg(res.error);
        setEmbedModelError(true);
      } else {
        const dim = res.embed_dim ? ` (${res.embed_dim}-dim)` : '';
        setEmbedModelMsg(
          res.reindex_required
            ? `Saved${dim} — reindex this workspace so query and document vectors match`
            : `Saved${dim}`,
        );
        setTimeout(() => setEmbedModelMsg(''), res.reindex_required ? 6000 : 3000);
      }
    } catch (e) {
      setEmbedModelMsg(e instanceof Error ? e.message : String(e));
      setEmbedModelError(true);
    }
    setEmbedModelBusy(false);
  };

  const refreshOcKeyStatus = () => {
    api.settings.opencodeKey.status().then((s) => {
      setOcKeyConfigured(s.configured);
      setOcKeyMasked(s.masked ?? null);
    }).catch(() => {});
  };

  const saveOcKey = async () => {
    const key = ocKeyInput.trim();
    if (!key || ocKeyBusy) return;
    setOcKeyBusy(true);
    setOcKeyIsError(false);
    setOcKeyMsg('Validating…');
    try {
      const res = await api.settings.opencodeKey.save(key);
      if (res.error) {
        setOcKeyMsg(res.error);
        setOcKeyIsError(true);
      } else {
        setOcKeyInput('');
        setShowKey(false);
        refreshOcKeyStatus();
        setOcKeyMsg('Key saved');
        setTimeout(() => setOcKeyMsg(''), 3000);
      }
    } catch (e) {
      setOcKeyMsg(e instanceof Error ? e.message : String(e));
      setOcKeyIsError(true);
    } finally {
      setOcKeyBusy(false);
    }
  };

  const removeOcKey = async () => {
    if (ocKeyBusy) return;
    setOcKeyBusy(true);
    setOcKeyIsError(false);
    try {
      const res = await api.settings.opencodeKey.remove();
      if (res.error) {
        setOcKeyMsg(res.error);
        setOcKeyIsError(true);
      } else {
        refreshOcKeyStatus();
        setOcKeyMsg('Key removed');
        setTimeout(() => setOcKeyMsg(''), 3000);
      }
    } catch (e) {
      setOcKeyMsg(e instanceof Error ? e.message : String(e));
      setOcKeyIsError(true);
    } finally {
      setOcKeyBusy(false);
    }
  };

  const themeOptions: { value: Theme; label: string }[] = [
    { value: 'light', label: 'Light' },
    { value: 'dark', label: 'Night' },
  ];

  const reloadPrompts = useCallback(async () => {
    try {
      const data = await api.prompts.list();
      setPrompts(data.prompts || []);
    } catch {
      setPrompts([]);
    }
  }, []);

  const createPrompt = async () => {
    setPromptMsg('');
    setPromptError(false);
    try {
      const res = await api.prompts.create({
        name: newPrompt.name,
        command: newPrompt.command,
        template: newPrompt.template,
        description: newPrompt.description || undefined,
      });
      if (res.error) {
        setPromptMsg(res.error);
        setPromptError(true);
        return;
      }
      setNewPrompt({ name: '', command: '', template: '', description: '' });
      await reloadPrompts();
      window.dispatchEvent(new CustomEvent('palimind:prompts-changed'));
      setPromptMsg('Prompt saved — type / in the composer to use it');
      setTimeout(() => setPromptMsg(''), 4000);
    } catch (e) {
      setPromptMsg(e instanceof Error ? e.message : String(e));
      setPromptError(true);
    }
  };

  const saveEditedPrompt = async () => {
    if (!editingPrompt) return;
    setPromptMsg('');
    setPromptError(false);
    try {
      const res = await api.prompts.update(editingPrompt.id, {
        name: editingPrompt.name,
        command: editingPrompt.command,
        template: editingPrompt.template,
        description: editingPrompt.description || undefined,
      });
      if (res.error) {
        setPromptMsg(res.error);
        setPromptError(true);
        return;
      }
      setEditingPrompt(null);
      await reloadPrompts();
      window.dispatchEvent(new CustomEvent('palimind:prompts-changed'));
    } catch (e) {
      setPromptMsg(e instanceof Error ? e.message : String(e));
      setPromptError(true);
    }
  };

  const deletePrompt = async (promptId: string) => {
    try {
      const res = await api.prompts.remove(promptId);
      if (res.error) {
        addToast(res.error, { tone: 'error' });
        return;
      }
      await reloadPrompts();
      window.dispatchEvent(new CustomEvent('palimind:prompts-changed'));
    } catch {
      addToast('Could not delete the prompt', { tone: 'error' });
    }
  };

  const enableNotifications = () => {
    if (typeof Notification === 'undefined') {
      addToast('Notifications are not available here.', { tone: 'warning' });
      return;
    }
    void Notification.requestPermission().then((state) => {
      setPermission(state);
      addToast(
        state === 'granted' ? 'Notifications enabled' : 'Notifications were not enabled',
        { tone: state === 'granted' ? 'success' : 'warning' },
      );
    });
  };

  if (!open) return null;

  const voiceAuto = isAutoSpeakOn(null);
  const voiceName = getVoice(null);

  return (
    <div ref={rootRef} className="settings-page" role="dialog" aria-modal="true" aria-label="Settings">
      <header className="settings-page-header">
        <h2>Settings</h2>
        <div className="settings-page-search">
          <Search size={15} />
          <input
            type="text"
            placeholder="Search settings…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search settings"
          />
        </div>
        <button
          type="button"
          className="settings-page-close"
          onClick={close}
          aria-label="Close settings"
          title="Close settings"
        >
          <kbd>Esc</kbd>
          <X size={14} />
        </button>
      </header>

      <div className="settings-page-body">
        <nav className="settings-nav" role="tablist" aria-label="Settings sections">
          {filteredNav.nav.map((s) => (
            <button
              key={s.key}
              id={`settings-tab-${s.key}`}
              type="button"
              role="tab"
              aria-selected={section === s.key}
              aria-controls={`settings-panel-${s.key}`}
              className={`settings-nav-item${section === s.key ? ' active' : ''}`}
              onClick={() => selectSection(s.key)}
            >
              {s.icon}
              <span>{s.label}</span>
              {s.key === 'opencode' && (
                <span
                  className={`settings-nav-status${ocKeyConfigured ? ' on' : ''}`}
                  aria-hidden="true"
                />
              )}
            </button>
          ))}
          {filteredNav.empty && (
            <p className="settings-nav-empty">No settings match “{search}”.</p>
          )}
        </nav>

        <div className="settings-pane">
          {/* ── Appearance ─────────────────────────────────────────── */}
          <div
            className="settings-section"
            id="settings-panel-appearance"
            role="tabpanel"
            aria-labelledby="settings-tab-appearance"
            hidden={section !== 'appearance'}
          >
            <SectionHeader title="Appearance">
              Applies instantly.
            </SectionHeader>
            <div className="settings-card">
              <div className="settings-card-title">Theme</div>
              <div className="settings-theme-grid">
                {themeOptions.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    className={`settings-theme-card${theme === opt.value ? ' active' : ''}`}
                    aria-pressed={theme === opt.value}
                    onClick={() => setTheme(opt.value)}
                  >
                    <span className={`settings-theme-swatch ${opt.value}`} aria-hidden="true" />
                    <span className="settings-theme-meta">
                      <span>{opt.label}</span>
                      {theme === opt.value && (
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M20 6 9 17l-5-5" />
                        </svg>
                      )}
                    </span>
                  </button>
                ))}
              </div>
              <div className="settings-field">
                <span className="settings-field-label">Interface style</span>
                <SegmentedControl<UiStyle>
                  value={uiStyle}
                  ariaLabel="Interface style"
                  options={[
                    { value: 'pixel', label: 'Pixel' },
                    { value: 'classic', label: 'Classic' },
                  ]}
                  onChange={(next) => {
                    setUiStyle(next);
                    applyUiStyle(next);
                  }}
                />
              </div>
            </div>
            <div className="settings-card">
              <div className="settings-card-title">Motion &amp; pixel accents</div>
              <p className="settings-hint">
                Small step-timed marks for status and progress.
              </p>
              <Toggle
                checked={pixelAccents === 'on'}
                onChange={(on) => {
                  const next: PixelAccents = on ? 'on' : 'off';
                  setPixelAccents(next);
                  applyPixelAccents(next);
                }}
                title="Pixel accents"
                description="Status, streaming and progress."
              />
              <div className="settings-field">
                <span className="settings-field-label">Motion</span>
                <SegmentedControl<MotionSetting>
                  value={motion}
                  ariaLabel="Motion preference"
                  options={[
                    { value: 'system', label: 'System' },
                    { value: 'full', label: 'Full' },
                    { value: 'reduced', label: 'Reduced' },
                  ]}
                  onChange={(next) => {
                    setMotion(next);
                    applyMotion(next);
                  }}
                />
              </div>
            </div>
            <div className="settings-card">
              <div className="settings-card-title">Your name</div>
              <p className="settings-hint">
                Used for the greeting. Stored locally.
              </p>
              <div className="settings-field">
                <label htmlFor="settings-user-name">What should we call you?</label>
                <input
                  id="settings-user-name"
                  className="settings-input"
                  type="text"
                  placeholder="e.g. Pakshal"
                  value={profileName}
                  maxLength={40}
                  autoComplete="given-name"
                  onChange={(e) => {
                    setProfileName(e.target.value);
                    setUserName(e.target.value);
                  }}
                />
              </div>
            </div>
          </div>

          {/* ── Voice ──────────────────────────────────────────────── */}
          <div
            className="settings-section"
            id="settings-panel-voice"
            role="tabpanel"
            aria-labelledby="settings-tab-voice"
            hidden={section !== 'voice'}
          >
            <SectionHeader title="Voice output">
              Speak assistant replies with the local voice model. Every reply also has a
              speaker button to play or stop it on demand.
            </SectionHeader>
            <div className="settings-card" key={voiceTick}>
              <div className="settings-card-title">Text-to-speech</div>
              <Toggle
                checked={voiceAuto}
                onChange={(value) => {
                  setAutoSpeak(value);
                  setVoiceTick((tick) => tick + 1);
                }}
                title="Speak replies automatically"
                description="Plays each finished answer aloud."
              />
              <div className="settings-field">
                <span className="settings-field-label">Voice</span>
                <Select
                  aria-label="Default voice"
                  value={voiceName}
                  onChange={(e) => {
                    setVoice(e.target.value);
                    setVoiceTick((tick) => tick + 1);
                  }}
                >
                  {TTS_VOICES.map((voice) => (
                    <option key={voice.id} value={voice.id}>
                      {voice.label}
                    </option>
                  ))}
                </Select>
              </div>
              <p className="settings-hint">
                Synthesis runs locally (Kokoro). {voiceName === DEFAULT_TTS_VOICE ? '' : ''}
              </p>
            </div>
            <div className="settings-card">
              <div className="settings-card-title">Try it</div>
              <p className="settings-hint">
                Open any assistant message and press the speaker button under it.
              </p>
              <Button
                size="sm"
                variant="secondary"
                onClick={async () => {
                  try {
                    const res = await api.voice.synthesize(
                      'Voice output is ready. This is your local assistant speaking.',
                      getVoice(null),
                    );
                    const url = URL.createObjectURL(res);
                    const audio = new Audio(url);
                    audio.onended = () => URL.revokeObjectURL(url);
                    void audio.play();
                  } catch {
                    addToast('Voice synthesis is not available', { tone: 'warning' });
                  }
                }}
              >
                Play a sample
              </Button>
            </div>
            <div className="settings-card">
              <div className="settings-card-title">Speech-to-text</div>
              <div className="settings-field">
                <label htmlFor="stt-model">Whisper model</label>
                <SettingsSelect
                  id="stt-model"
                  value={sttModel}
                  onChange={setSttModel}
                  options={
                    sttOptions.length === 0
                      ? [{ value: sttModel, label: sttModel }]
                      : sttOptions.map((o) => ({
                          value: o.id,
                          label: o.label,
                          description: `~${o.size_mb} MB — ${o.note}`,
                        }))
                  }
                />
              </div>
              <div className="settings-actions-row">
                <button className="action-btn primary" onClick={saveSttModel} disabled={sttBusy}>
                  {sttBusy ? 'Saving…' : 'Save'}
                </button>
                <Feedback message={sttMsg} isError={sttError} />
              </div>
            </div>
          </div>

          {/* ── Prompt library ─────────────────────────────────────── */}
          <div
            className="settings-section"
            id="settings-panel-prompts"
            role="tabpanel"
            aria-labelledby="settings-tab-prompts"
            hidden={section !== 'prompts'}
          >
            <SectionHeader title="Prompt library">
              Save reusable prompts with <code>{'{variables}'}</code>. They appear as slash
              commands in the composer (<code>/name</code>) and in the command palette.
            </SectionHeader>

            <div className="settings-card">
              <div className="settings-card-title">New prompt</div>
              <div className="settings-field">
                <label htmlFor="prompt-new-name">Name</label>
                <input
                  id="prompt-new-name"
                  className="settings-input"
                  type="text"
                  placeholder="Paper summary"
                  value={newPrompt.name}
                  onChange={(e) => setNewPrompt({ ...newPrompt, name: e.target.value })}
                />
              </div>
              <div className="settings-field">
                <label htmlFor="prompt-new-command">Slash command</label>
                <input
                  id="prompt-new-command"
                  className="settings-input"
                  type="text"
                  placeholder="paper-summary"
                  value={newPrompt.command}
                  onChange={(e) => setNewPrompt({ ...newPrompt, command: e.target.value })}
                />
              </div>
              <div className="settings-field">
                <label htmlFor="prompt-new-template">Template</label>
                <textarea
                  id="prompt-new-template"
                  className="settings-input"
                  placeholder={'Summarise {url} in three bullet points for a {audience} audience.'}
                  value={newPrompt.template}
                  onChange={(e) => setNewPrompt({ ...newPrompt, template: e.target.value })}
                />
              </div>
              <div className="settings-actions-row">
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => void createPrompt()}
                  disabled={!newPrompt.name.trim() || !newPrompt.template.trim()}
                >
                  Save prompt
                </Button>
                <Feedback message={promptMsg} isError={promptError} />
              </div>
              {templateVariables(newPrompt.template).length > 0 && (
                <p className="settings-hint">
                  Variables: {templateVariables(newPrompt.template).map((v) => `{${v}}`).join(', ')}
                </p>
              )}
            </div>

            {prompts.length > 0 && (
              <div className="settings-card">
                <div className="settings-card-title">Saved prompts</div>
                <div className="settings-voice-grid">
                  {prompts.map((prompt) =>
                    editingPrompt?.id === prompt.id ? (
                      <div key={prompt.id} className="settings-prompt-row">
                        <div className="settings-prompt-row-fields">
                          <div className="settings-field">
                            <label htmlFor={`prompt-name-${prompt.id}`}>Name</label>
                            <input
                              id={`prompt-name-${prompt.id}`}
                              className="settings-input"
                              type="text"
                              value={editingPrompt.name}
                              onChange={(e) =>
                                setEditingPrompt({ ...editingPrompt, name: e.target.value })
                              }
                            />
                          </div>
                          <div className="settings-field">
                            <label htmlFor={`prompt-cmd-${prompt.id}`}>Slash command</label>
                            <input
                              id={`prompt-cmd-${prompt.id}`}
                              className="settings-input"
                              type="text"
                              value={editingPrompt.command}
                              onChange={(e) =>
                                setEditingPrompt({ ...editingPrompt, command: e.target.value })
                              }
                            />
                          </div>
                          <div className="settings-field">
                            <label htmlFor={`prompt-tpl-${prompt.id}`}>Template</label>
                            <textarea
                              id={`prompt-tpl-${prompt.id}`}
                              value={editingPrompt.template}
                              onChange={(e) =>
                                setEditingPrompt({ ...editingPrompt, template: e.target.value })
                              }
                            />
                          </div>
                          <div className="settings-field">
                            <label htmlFor={`prompt-desc-${prompt.id}`}>Description</label>
                            <input
                              id={`prompt-desc-${prompt.id}`}
                              className="settings-input"
                              type="text"
                              value={editingPrompt.description}
                              onChange={(e) =>
                                setEditingPrompt({ ...editingPrompt, description: e.target.value })
                              }
                            />
                          </div>
                        </div>
                        <div className="settings-prompt-row-actions">
                          <Button
                            size="sm"
                            variant="primary"
                            disabled={!editingPrompt.name.trim() || !editingPrompt.template.trim()}
                            onClick={() => void saveEditedPrompt()}
                          >
                            Save
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setEditingPrompt(null)}>
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div key={prompt.id} className="settings-prompt-row">
                        <div className="settings-prompt-row-head">
                          <code>/{prompt.command}</code>
                          <strong>{prompt.name}</strong>
                          {prompt.description && (
                            <span className="settings-prompt-row-desc">{prompt.description}</span>
                          )}
                        </div>
                        <pre className="settings-prompt-row-template settings-hint-inline">
                          {prompt.template}
                        </pre>
                        <div className="settings-prompt-row-actions">
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() =>
                              setEditingPrompt({
                                id: prompt.id,
                                name: prompt.name,
                                command: prompt.command,
                                description: prompt.description ?? '',
                                template: prompt.template,
                              })
                            }
                          >
                            Edit
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => void deletePrompt(prompt.id)}>
                            Delete
                          </Button>
                        </div>
                      </div>
                    ),
                  )}
                </div>
              </div>
            )}
          </div>

          {/* ── OpenCode ───────────────────────────────────────────── */}
          <div
            className="settings-section"
            id="settings-panel-opencode"
            role="tabpanel"
            aria-labelledby="settings-tab-opencode"
            hidden={section !== 'opencode'}
          >
            <SectionHeader title="OpenCode">
              Connect Palimind to OpenCode&apos;s cloud models. A key is optional —
              local Ollama models keep working without one.
            </SectionHeader>

            <div className="settings-card">
              <div className="settings-card-title">Connection</div>
              <div className="settings-status-row">
                <span className={`settings-dot${ocKeyConfigured ? ' on' : ''}`} aria-hidden="true" />
                <span className="settings-status-text">
                  {ocKeyConfigured ? 'Connected' : 'Not configured'}
                </span>
                {ocKeyConfigured && ocKeyMasked && (
                  <code className="settings-masked" title="Last characters of the stored key">
                    {ocKeyMasked}
                  </code>
                )}
              </div>

              <div className="settings-field">
                <label htmlFor="opencode-api-key">API key</label>
                <div className="settings-input-wrap">
                  <input
                    id="opencode-api-key"
                    type={showKey ? 'text' : 'password'}
                    className="settings-input"
                    placeholder="Paste your OpenCode API key"
                    value={ocKeyInput}
                    autoComplete="new-password"
                    spellCheck={false}
                    onChange={(e) => setOcKeyInput(e.target.value)}
                  />
                  <button
                    type="button"
                    className="settings-input-btn"
                    aria-label={showKey ? 'Hide key' : 'Show key'}
                    title={showKey ? 'Hide key' : 'Show key'}
                    onClick={() => setShowKey((v) => !v)}
                  >
                    {showKey ? (
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8" />
                        <path d="M6.7 6.7C4.6 8.1 3 10.2 2 12c1.7 3 5.3 6 10 6 1.6 0 3-.3 4.3-.9M9.9 5.2A9.7 9.7 0 0 1 12 5c4.7 0 8.3 3 10 6-.6 1-1.4 2.1-2.5 3.1" />
                      </svg>
                    ) : (
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M2 12c1.7-3 5.3-6 10-6s8.3 3 10 6c-1.7 3-5.3 6-10 6s-8.3-3-10-6z" />
                        <circle cx="12" cy="12" r="2.5" />
                      </svg>
                    )}
                  </button>
                </div>
              </div>

              <div className="settings-actions-row">
                <button
                  className="action-btn primary"
                  onClick={saveOcKey}
                  disabled={ocKeyBusy || !ocKeyInput.trim()}
                >
                  {ocKeyBusy ? 'Saving…' : 'Save key'}
                </button>
                {ocKeyConfigured && (
                  <button className="action-btn ghost" onClick={removeOcKey} disabled={ocKeyBusy}>
                    Remove
                  </button>
                )}
                <Feedback message={ocKeyMsg} isError={ocKeyIsError} />
              </div>
            </div>

            <p className="settings-hint-inline">
              Stored locally with owner-only permissions and sent only to the OpenCode
              API. A key already configured with the OpenCode CLI is detected
              automatically.
            </p>
          </div>

          {/* ── Models ─────────────────────────────────────────────── */}
          <div
            className="settings-section"
            id="settings-panel-models"
            role="tabpanel"
            aria-labelledby="settings-tab-models"
            hidden={section !== 'models'}
          >
            <SectionHeader title="Default Models">
              Configure the local models used for folder indexing. All models run
              locally via Ollama.
            </SectionHeader>

            <div className="settings-card">
              <div className="settings-card-title">Embedding model</div>
              <div className="settings-field">
                <label htmlFor="embed-model">Indexing model</label>
                <SettingsSelect
                  id="embed-model"
                  value={embedModel}
                  onChange={setEmbedModel}
                  options={[
                    { value: 'bge-m3', label: 'BGE-M3', description: '566M params, 1024-dim (multilingual, recommended)' },
                    { value: 'nomic-embed-text', label: 'Nomic Embed Text', description: '137M params, 768-dim' },
                    { value: 'nomic-embed-text:v1.5', label: 'Nomic Embed Text v1.5', description: '137M params, 768-dim (better quality)' },
                    { value: 'mxbai-embed-large', label: 'MixedBread Embed Large', description: '335M params, 1024-dim' },
                    { value: 'all-minilm', label: 'All-MiniLM', description: '23M params, 384-dim (fastest, lower quality)' },
                  ]}
                />
              </div>
              <div className="settings-actions-row">
                <button className="action-btn primary" onClick={saveEmbedModel} disabled={embedModelBusy}>
                  {embedModelBusy ? 'Saving…' : 'Save'}
                </button>
                <Feedback message={embedModelMsg} isError={embedModelError} />
              </div>
            </div>

            <p className="settings-hint-inline">
              Pull a model first with <code>ollama pull &lt;model&gt;</code> if it is not installed.
              After changing the embedding model, re-index your folders to apply.
            </p>
          </div>

          {/* ── Notifications ──────────────────────────────────────── */}
          <div
            className="settings-section"
            id="settings-panel-notifications"
            role="tabpanel"
            aria-labelledby="settings-tab-notifications"
            hidden={section !== 'notifications'}
          >
            <SectionHeader title="Notifications">
              Get a desktop notification when an agent stops to ask a question or waits
              for approval.
            </SectionHeader>
            <div className="settings-card">
              <div className="settings-card-title">Desktop notifications</div>
              <div className="settings-status-row">
                <span
                  className={`settings-dot${permission === 'granted' ? ' on' : ''}`}
                  aria-hidden="true"
                />
                <span className="settings-status-text">
                  {permission === 'granted'
                    ? 'Enabled'
                    : permission === 'denied'
                      ? 'Blocked in this browser — allow notifications for PaliMind in system settings'
                      : 'Not enabled'}
                </span>
              </div>
              <div className="settings-actions-row">
                <Button
                  size="sm"
                  variant="primary"
                  onClick={enableNotifications}
                  disabled={permission === 'granted'}
                >
                  {permission === 'granted' ? 'Enabled' : 'Enable notifications'}
                </Button>
              </div>
            </div>
          </div>

          {/* ── Desktop / Computer use ─────────────────────────────── */}
          <div
            className="settings-section"
            id="settings-panel-desktop"
            role="tabpanel"
            aria-labelledby="settings-tab-desktop"
            hidden={section !== 'desktop'}
          >
            <SectionHeader title="Computer use">
              Let an agent see and operate any app on your Linux desktop through the
              accessibility tree. On by default; protected system apps are always
              excluded and every action is audited.
            </SectionHeader>

            <div className="settings-card">
              <div className="settings-card-title">How to use</div>
              <ol className="settings-howto">
                <li>
                  <strong>Already on.</strong> Computer use is enabled by default and
                  works with any app. Set <code>PALIMIND_DESKTOP_ENABLE=0</code> to turn
                  it off.
                </li>
                <li>
                  <strong>Pick any app.</strong> Open the popup and choose a window from
                  the <strong>Target</strong> list — or drag a screen area. Shells,
                  keyrings, polkit prompts, lock screens and Palimind itself are always
                  excluded.
                </li>
                <li>
                  <strong>Ask or Act.</strong> Ask is read-only. Act performs the task
                  and shows an <strong>Approve / Deny</strong> card for every mutating
                  step.
                </li>
                <li>
                  <strong>Optional allowlist.</strong> To restrict the agent, set{' '}
                  <code>PALIMIND_DESKTOP_ALLOWED_APPS</code> and restart the backend.
                  Empty means any app.
                </li>
                <li>
                  <strong>Stop instantly.</strong> Press{' '}
                  <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>Escape</kbd>, the popup's
                  Stop button, or the tray item to release held input.
                </li>
              </ol>
              <div className="settings-actions-row">
                <button
                  className="action-btn primary"
                  onClick={() => {
                    void import('@tauri-apps/api/core')
                      .then(({ invoke }) => invoke('open_computer_use'))
                      .catch(() => setDesktopMsg('Open the desktop app to use the popup.'));
                  }}
                >
                  Open Computer Use
                </button>
              </div>
            </div>

            <div className="settings-card">
              <div className="settings-card-title">Status</div>
              {desktop?.ok && desktop.status ? (
                <ul className="settings-hint-inline" style={{ lineHeight: 1.7 }}>
                  <li>
                    Session: <strong>{desktop.status.platform}</strong> /{' '}
                    {desktop.status.session_type}
                  </li>
                  <li>
                    Accessibility:{' '}
                    <strong>{desktop.status.permissions?.accessibility?.state ?? 'unknown'}</strong>
                  </li>
                  <li>
                    Kernel input:{' '}
                    <strong>
                      {desktop.status.kernel_input?.accessible
                        ? 'available'
                        : desktop.status.kernel_input?.detail ?? 'unavailable'}
                    </strong>
                  </li>
                  <li>
                    Wayland capture:{' '}
                    <strong>
                      {desktop.status.screencast_token
                        ? 'ScreenCast approved'
                        : 'ScreenCast approval needed on first capture'}
                    </strong>
                  </li>
                  <li>
                    Enabled: <strong>{String(desktop.status.policy?.enabled)}</strong> · Actions:{' '}
                    {desktop.status.policy?.rate_limit_per_min ?? 30}/min · Stopped:{' '}
                    {String(desktop.status.policy?.stopped)}
                  </li>
                </ul>
              ) : (
                <p className="settings-hint-inline">
                  {desktop?.enabled
                    ? 'The native daemon is unavailable. Build it with `make desktop-native`.'
                    : 'Computer use is off. It is on by default; check PALIMIND_DESKTOP_ENABLE.'}
                </p>
              )}
              <div className="settings-actions-row">
                <button className="action-btn" onClick={refreshDesktop} disabled={desktopBusy}>
                  {desktopBusy ? 'Checking…' : 'Check again'}
                </button>
                <button
                  className="action-btn"
                  onClick={async () => {
                    await api.desktop.stop().catch(() => {});
                    await refreshDesktop();
                  }}
                  disabled={desktopBusy || !desktop?.enabled}
                >
                  Stop desktop control
                </button>
                <Feedback message={desktopMsg} isError={!!desktopMsg} />
              </div>
            </div>

            <div className="settings-card">
              <div className="settings-card-title">Ghost cursor</div>
              <Toggle
                title="Show a click-through target hint"
                description="Draws a crosshair/highlight at a selected region without moving the real pointer. The hint never receives clicks."
                checked={ghostCursor}
                onChange={(value) => {
                  setGhostCursor(value);
                  localStorage.setItem('palimind:ghost-cursor', value ? '1' : '0');
                  if (!value) {
                    void import('@tauri-apps/api/core')
                      .then(({ invoke }) => invoke('hide_ghost_cursor'))
                      .catch(() => {});
                  }
                }}
              />
            </div>

            <div className="settings-card">
              <div className="settings-card-title">Allowed apps</div>
              <p className="settings-hint-inline">
                Any app is allowed by default (protected processes stay excluded). To
                restrict the agent to a few apps, set this and restart the backend:
              </p>
              <pre className="settings-hint-inline">
{`PALIMIND_DESKTOP_ALLOWED_APPS=gnome-calculator,gnome-text-editor`}
              </pre>
              <p className="settings-hint-inline">
                System shells, keyrings, polkit prompts, lock screens and Palimind
                itself cannot be allowed. A per-agent{' '}
                <strong>desktop_allowed_apps</strong> list narrows this further.
              </p>
            </div>

            <div className="settings-card">
              <div className="settings-card-title">Recent actions</div>
              {desktopAudit.length === 0 ? (
                <p className="settings-hint-inline">No actions have been recorded yet.</p>
              ) : (
                <ul className="settings-hint-inline" style={{ lineHeight: 1.7 }}>
                  {desktopAudit.map((entry, index) => (
                    <li key={`${String(entry.ts_ms)}-${index}`}>
                      {new Date(Number(entry.ts_ms)).toLocaleTimeString()} ·{' '}
                      <strong>{String(entry.command)}</strong>
                      {entry.action ? ` ${String(entry.action)}` : ''}
                      {entry.app ? ` on ${String(entry.app)}` : ''} ·{' '}
                      {entry.ok ? 'ok' : `denied (${String(entry.code)})`}
                    </li>
                  ))}
                </ul>
              )}
              <p className="settings-hint-inline">
                Audit entries never contain typed text or field values, only a salted
                fingerprint and length.
              </p>
            </div>

            <p className="settings-hint-inline">
              Agent access is granted per agent in the agent wizard:{' '}
              <strong>desktop_access</strong> to observe and{' '}
              <strong>desktop_control</strong> to act. Mutating actions still ask for
              approval and can be stopped at any time.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
