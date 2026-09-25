import { useEffect, useState } from 'react';
import { useApp } from '../AppContext';
import { api } from '../api';

export default function SettingsModal() {
  const { theme, setTheme } = useApp();
  const [personaName, setPersonaName] = useState('');
  const [personaPrompt, setPersonaPrompt] = useState('');
  const [personaStatus, setPersonaStatus] = useState('');
  const [ocKeyConfigured, setOcKeyConfigured] = useState(false);
  const [ocKeyMasked, setOcKeyMasked] = useState<string | null>(null);
  const [ocKeyInput, setOcKeyInput] = useState('');
  const [ocKeyMsg, setOcKeyMsg] = useState('');
  const [ocKeyIsError, setOcKeyIsError] = useState(false);
  const [ocKeyBusy, setOcKeyBusy] = useState(false);
  const [sttModel, setSttModel] = useState('base.en');
  const [sttOptions, setSttOptions] = useState<
    { id: string; label: string; size_mb: number; note: string }[]
  >([]);
  const [sttMsg, setSttMsg] = useState('');
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

  const saveSttModel = async () => {
    setSttBusy(true);
    setSttMsg('');
    try {
      const res = await api.settings.voice.save({ stt_whisper_model: sttModel });
      setSttMsg(res.error ? `Error: ${res.error}` : 'Saved');
    } catch (e) {
      setSttMsg(`Error: ${e instanceof Error ? e.message : e}`);
    }
    setSttBusy(false);
    setTimeout(() => setSttMsg(''), 2500);
  };

  const close = () => {
    const modal = document.getElementById('settings-modal');
    if (modal) modal.style.display = 'none';
  };

  useEffect(() => {
    const modal = document.getElementById('settings-modal');
    if (!modal) return;
    const handler = (e: MouseEvent) => {
      if (e.target === modal) close();
    };
    modal.addEventListener('click', handler);
    return () => modal.removeEventListener('click', handler);
  }, []);

  const savePersona = async () => {
    setPersonaStatus('Saving...');
    try {
      const res = await api.config.setPersona({
        persona_name: personaName,
        persona_system_prompt: personaPrompt,
      });
      setPersonaStatus(res.error ? `Error: ${res.error}` : 'Saved');
    } catch (e) {
      setPersonaStatus(`Error: ${e instanceof Error ? e.message : e}`);
    }
    setTimeout(() => setPersonaStatus(''), 2500);
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
    setOcKeyMsg('Validating...');
    try {
      const res = await api.settings.opencodeKey.save(key);
      if (res.error) {
        setOcKeyMsg(res.error);
        setOcKeyIsError(true);
      } else {
        setOcKeyInput('');
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

  return (
    <div id="settings-modal" className="modal" role="dialog" aria-modal="true" aria-labelledby="settings-title" style={{ display: 'none' }}>
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
          <div className="settings-group">
            <label>Theme Mode</label>
            <div className="theme-switch-container">
              <button
                className={`theme-toggle-btn${theme === 'light' ? ' active' : ''}`}
                onClick={() => setTheme('light')}
              >
                Light Mode
              </button>
              <button
                className={`theme-toggle-btn${theme === 'dark' ? ' active' : ''}`}
                onClick={() => setTheme('dark')}
              >
                Night Mode
              </button>
            </div>
          </div>

          <div className="settings-group">
            <label htmlFor="opencode-api-key">OpenCode API Key</label>
            <p className="settings-hint">
              Stored in the global OpenCode auth file and shared with the
              OpenCode CLI. Used by Palimind&apos;s Zen proxy for chat models.
            </p>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span
                aria-hidden="true"
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  flexShrink: 0,
                  background: ocKeyConfigured ? '#4ade80' : 'var(--text-muted)',
                  opacity: ocKeyConfigured ? 1 : 0.55,
                }}
              />
              <span className="settings-status">
                {ocKeyConfigured
                  ? `Connected (${ocKeyMasked || '…'})`
                  : 'Not configured'}
              </span>
            </div>
            <input
              id="opencode-api-key"
              type="password"
              className="settings-input"
              placeholder="Paste your OpenCode API key"
              value={ocKeyInput}
              autoComplete="new-password"
              onChange={(e) => setOcKeyInput(e.target.value)}
            />
            <div className="settings-actions">
              <button
                className="action-btn primary"
                onClick={saveOcKey}
                disabled={ocKeyBusy || !ocKeyInput.trim()}
              >
                {ocKeyBusy ? 'Saving...' : 'Save Key'}
              </button>
              {ocKeyConfigured && (
                <button
                  className="action-btn ghost"
                  onClick={removeOcKey}
                  disabled={ocKeyBusy}
                >
                  Remove
                </button>
              )}
              {ocKeyMsg && (
                <span
                  className="settings-status"
                  style={ocKeyIsError ? { color: 'var(--danger-strong)' } : undefined}
                >
                  {ocKeyMsg}
                </span>
              )}
            </div>
          </div>

          <div className="settings-group">
            <label htmlFor="stt-model">Speech-to-text model (microphone)</label>
            <p className="settings-hint">
              Local Whisper model used for voice input. The first use downloads it
              (progress appears in the banner at the top). English-only &ldquo;.en&rdquo;
              models are faster on CPU.
            </p>
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
            <div className="settings-actions">
              <button className="action-btn primary" onClick={saveSttModel} disabled={sttBusy}>
                {sttBusy ? 'Saving...' : 'Save'}
              </button>
              {sttMsg && <span className="settings-status">{sttMsg}</span>}
            </div>
          </div>

          <div className="settings-group">
            <label>Persona</label>
            <p className="settings-hint">
              Customizes how the assistant responds in this knowledge base. Leave empty to
              use the default behavior.
            </p>
            <input
              className="settings-input"
              placeholder="Persona name (optional)"
              value={personaName}
              onChange={(e) => setPersonaName(e.target.value)}
            />
            <textarea
              className="settings-textarea"
              rows={5}
              placeholder={'You are a concise research assistant. Always answer with bullet points...'}
              value={personaPrompt}
              onChange={(e) => setPersonaPrompt(e.target.value)}
            />
            <div className="settings-actions">
              <button className="action-btn primary" onClick={savePersona}>Save Persona</button>
              {personaStatus && <span className="settings-status">{personaStatus}</span>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
