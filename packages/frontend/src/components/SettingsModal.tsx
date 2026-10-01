import { useEffect, useState, type ReactNode } from 'react';
import { useApp } from '../AppContext';
import { api } from '../api';
import type { Theme } from '../types';

type SectionKey = 'appearance' | 'opencode' | 'voice' | 'persona';

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
    key: 'voice',
    label: 'Voice',
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <rect x="9" y="2.5" width="6" height="11" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3.5" />
      </svg>
    ),
  },
  {
    key: 'persona',
    label: 'Persona',
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="8" r="3.5" />
        <path d="M4.5 20.5a7.5 7.5 0 0 1 15 0" />
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
  const [section, setSection] = useState<SectionKey>('appearance');
  const [personaName, setPersonaName] = useState('');
  const [personaPrompt, setPersonaPrompt] = useState('');
  const [personaStatus, setPersonaStatus] = useState('');
  const [personaError, setPersonaError] = useState(false);
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

  useEffect(() => {
    api.config.get().then((cfg) => {
      if (cfg.persona_name) setPersonaName(cfg.persona_name);
      if (cfg.persona_system_prompt) setPersonaPrompt(cfg.persona_system_prompt);
    }).catch(() => {});
    api.settings.opencodeKey.status().then((s) => {
      setOcKeyConfigured(s.configured);
      setOcKeyMasked(s.masked ?? null);
    }).catch(() => {});
    api.settings.voice.status().then((v) => {
      setSttModel(v.stt_whisper_model || 'base.en');
      setSttOptions(v.options || []);
    }).catch(() => {});
  }, []);

  const close = () => {
    const modal = document.getElementById('settings-modal');
    if (modal) modal.style.display = 'none';
    setShowKey(false);
  };

  useEffect(() => {
    const modal = document.getElementById('settings-modal');
    if (!modal) return;
    const handler = (e: MouseEvent) => {
      if (e.target === modal) {
        modal.style.display = 'none';
        setShowKey(false);
      }
    };
    modal.addEventListener('click', handler);
    return () => modal.removeEventListener('click', handler);
  }, []);

  const selectSection = (key: SectionKey) => {
    setSection(key);
    setOcKeyMsg('');
    setSttMsg('');
    setPersonaStatus('');
  };

  const savePersona = async () => {
    setPersonaStatus('Saving…');
    setPersonaError(false);
    try {
      const res = await api.config.setPersona({
        persona_name: personaName,
        persona_system_prompt: personaPrompt,
      });
      if (res.error) {
        setPersonaStatus(res.error);
        setPersonaError(true);
      } else {
        setPersonaStatus('Saved');
        setTimeout(() => setPersonaStatus(''), 2500);
      }
    } catch (e) {
      setPersonaStatus(e instanceof Error ? e.message : String(e));
      setPersonaError(true);
    }
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

  return (
    <div
      id="settings-modal"
      className="modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-title"
      style={{ display: 'none' }}
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
              id="settings-panel-voice"
              role="tabpanel"
              aria-labelledby="settings-tab-voice"
              hidden={section !== 'voice'}
            >
              <SectionHeader title="Voice">
                Pick the local Whisper model used for microphone input. The first use
                downloads it; English-only &ldquo;.en&rdquo; models are faster on CPU.
              </SectionHeader>

              <div className="settings-card">
                <div className="settings-card-title">Speech-to-text</div>
                <div className="settings-field">
                  <label htmlFor="stt-model">Model</label>
                  <select
                    id="stt-model"
                    className="settings-input"
                    value={sttModel}
                    onChange={(e) => setSttModel(e.target.value)}
                  >
                    {sttOptions.length === 0 && <option value={sttModel}>{sttModel}</option>}
                    {sttOptions.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.label} · ~{o.size_mb} MB — {o.note}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="settings-actions-row">
                  <button className="action-btn primary" onClick={saveSttModel} disabled={sttBusy}>
                    {sttBusy ? 'Saving…' : 'Save'}
                  </button>
                  <Feedback message={sttMsg} isError={sttError} />
                </div>
              </div>
            </div>

            <div
              className="settings-section"
              id="settings-panel-persona"
              role="tabpanel"
              aria-labelledby="settings-tab-persona"
              hidden={section !== 'persona'}
            >
              <SectionHeader title="Persona">
                Customize how the assistant responds in this knowledge base. Leave both
                fields empty to use the default behavior.
              </SectionHeader>

              <div className="settings-card">
                <div className="settings-card-title">Assistant</div>
                <div className="settings-field">
                  <label htmlFor="persona-name">Persona name</label>
                  <input
                    id="persona-name"
                    className="settings-input"
                    placeholder="Optional, e.g. Research Analyst"
                    value={personaName}
                    onChange={(e) => setPersonaName(e.target.value)}
                  />
                </div>
                <div className="settings-field">
                  <label htmlFor="persona-prompt">System prompt</label>
                  <textarea
                    id="persona-prompt"
                    className="settings-textarea"
                    rows={5}
                    placeholder="You are a concise research assistant. Always answer with bullet points…"
                    value={personaPrompt}
                    onChange={(e) => setPersonaPrompt(e.target.value)}
                  />
                </div>
                <div className="settings-actions-row">
                  <button className="action-btn primary" onClick={savePersona}>
                    Save persona
                  </button>
                  <Feedback message={personaStatus} isError={personaError} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
