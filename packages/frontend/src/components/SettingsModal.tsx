import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useApp } from '../AppContext';
import { api } from '../api';
import type { Theme } from '../types';
import { SegmentedControl, Toggle } from '../ui/primitives';
import {
  applyMotion,
  applyPixelAccents,
  readMotion,
  readPixelAccents,
  type MotionSetting,
  type PixelAccents,
} from '../design/usePixelMotion';
import { applyUiStyle, readUiStyle, type UiStyle } from '../design/uiStyle';
import { getUserName, setUserName } from '../utils/userName';
import SettingsSelect from './SettingsSelect';

type SectionKey = 'appearance' | 'opencode' | 'models';

interface SectionDef {
  key: SectionKey;
  label: string;
  icon: ReactNode;
}

const SECTIONS: SectionDef[] = [
  {
    key: 'appearance',
    label: 'Appearance',
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 3a9 9 0 0 1 0 18V3z" fill="currentColor" stroke="none" opacity="0.55" />
      </svg>
    ),
  },
  {
    key: 'opencode',
    label: 'OpenCode',
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
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
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

export default function SettingsModal() {
  const { theme, setTheme } = useApp();
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const [section, setSection] = useState<SectionKey>('appearance');
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
  const [embedModel, setEmbedModel] = useState('nomic-embed-text');
  const [embedModelMsg, setEmbedModelMsg] = useState('');
  const [embedModelError, setEmbedModelError] = useState(false);
  const [embedModelBusy, setEmbedModelBusy] = useState(false);
  const [profileName, setProfileName] = useState(getUserName);
  const [pixelAccents, setPixelAccents] = useState<PixelAccents>(readPixelAccents);
  const [motion, setMotion] = useState<MotionSetting>(readMotion);
  const [uiStyle, setUiStyle] = useState<UiStyle>(readUiStyle);

  useEffect(() => {
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
  }, []);

  const close = () => {
    setOpen(false);
    setShowKey(false);
  };

  useEffect(() => {
    const openSettings = () => setOpen(true);
    window.addEventListener('palimind:open-settings', openSettings);
    return () => window.removeEventListener('palimind:open-settings', openSettings);
  }, []);

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focusable = () =>
      Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
    focusable()[0]?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        close();
        return;
      }
      if (e.key !== 'Tab') return;
      const list = focusable();
      if (list.length === 0) return;
      const first = list[0];
      const last = list[list.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKey);
      restoreRef.current?.focus?.();
    };
  }, [open]);

  const selectSection = (key: SectionKey) => {
    setSection(key);
    setOcKeyMsg('');
    setSttMsg('');
    setEmbedModelMsg('');
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
        setEmbedModelMsg('Saved — reindex to apply');
        setTimeout(() => setEmbedModelMsg(''), 3000);
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

  const themeOptions: { value: Theme; label: string; hint: string }[] = [
    { value: 'light', label: 'Light', hint: 'Bright surfaces' },
    { value: 'dark', label: 'Night', hint: 'Low-light contrast' },
  ];

  if (!open) return null;

  return (
    <div
      ref={dialogRef}
      id="settings-modal"
      className="modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-title"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="modal-content">
        <div className="modal-header">
          <h2 id="settings-title">Settings</h2>
          <button className="icon-btn" title="Close Settings" aria-label="Close settings" onClick={close}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="modal-body">
          <nav className="settings-nav" role="tablist" aria-label="Settings sections">
            {SECTIONS.map((s) => (
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
          </nav>

          <div className="settings-pane">
            <div
              className="settings-section"
              id="settings-panel-appearance"
              role="tabpanel"
              aria-labelledby="settings-tab-appearance"
              hidden={section !== 'appearance'}
            >
              <SectionHeader title="Appearance">
                Choose how Palimind looks. The change applies instantly and is remembered
                on this device.
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
                        {theme === opt.value ? (
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M20 6 9 17l-5-5" />
                          </svg>
                        ) : (
                          <span className="settings-theme-hint">{opt.hint}</span>
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
                  Pixel details are small, step-timed marks used for live status,
                  progress and one-shot success. Motion follows the system setting
                  unless you choose otherwise.
                </p>
                <Toggle
                  checked={pixelAccents === 'on'}
                  onChange={(on) => {
                    const next: PixelAccents = on ? 'on' : 'off';
                    setPixelAccents(next);
                    applyPixelAccents(next);
                  }}
                  title="Pixel accents"
                  description="Brand blink, live status, streaming caret and progress meter."
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
                  Used to personalise the greeting on the start screen. Stored only
                  on this device.
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
              <div className="settings-card">
                <div className="settings-card-title">Artifacts</div>
                <p className="settings-hint">
                  Artifacts are previewed in the right rail. Use the Artifacts page in the
                  sidebar to browse everything you have saved.
                </p>
              </div>
            </div>

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

            <div
              className="settings-section"
              id="settings-panel-models"
              role="tabpanel"
              aria-labelledby="settings-tab-models"
              hidden={section !== 'models'}
            >
              <SectionHeader title="Default Models">
                Configure the local models used for speech-to-text and folder indexing.
                All models run locally via Ollama.
              </SectionHeader>

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

              <div className="settings-card">
                <div className="settings-card-title">Embedding model</div>
                <div className="settings-field">
                  <label htmlFor="embed-model">Indexing model</label>
                  <SettingsSelect
                    id="embed-model"
                    value={embedModel}
                    onChange={setEmbedModel}
                    options={[
                      { value: 'nomic-embed-text', label: 'Nomic Embed Text', description: '137M params, 768-dim' },
                      { value: 'nomic-embed-text:v1.5', label: 'Nomic Embed Text v1.5', description: '137M params, 768-dim (better quality)' },
                      { value: 'BAAI/bge-base-en-v1.5', label: 'BGE Base English v1.5', description: '109M params, 768-dim' },
                      { value: 'BAAI/bge-small-en-v1.5', label: 'BGE Small English v1.5', description: '33M params, 384-dim (lightweight)' },
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
          </div>
        </div>
      </div>
    </div>
  );
}
