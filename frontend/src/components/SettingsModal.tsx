import { useEffect, useState } from 'react';
import { useApp } from '../AppContext';
import { api } from '../api';
import type { ModelItem } from '../types';

export default function SettingsModal() {
  const { theme, setTheme } = useApp();
  const [personaName, setPersonaName] = useState('');
  const [personaPrompt, setPersonaPrompt] = useState('');
  const [thinkingModel, setThinkingModel] = useState('');
  const [models, setModels] = useState<ModelItem[]>([]);
  const [personaStatus, setPersonaStatus] = useState('');
  const [thinkingStatus, setThinkingStatus] = useState('');

  useEffect(() => {
    api.config.get().then((cfg) => {
      if (cfg.persona_name) setPersonaName(cfg.persona_name);
      if (cfg.persona_system_prompt) setPersonaPrompt(cfg.persona_system_prompt);
      setThinkingModel(cfg.thinking_model || '');
    }).catch(() => {});
    api.models.list().then((d) => {
      if (d.models) setModels(d.models);
    }).catch(() => {});
  }, []);

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

  const saveThinking = async (modelId: string) => {
    setThinkingModel(modelId);
    setThinkingStatus('Saving...');
    try {
      const res = await api.config.setThinking(modelId);
      setThinkingStatus(res.error ? `Error: ${res.error}` : 'Saved');
    } catch (e) {
      setThinkingStatus(`Error: ${e instanceof Error ? e.message : e}`);
    }
    setTimeout(() => setThinkingStatus(''), 2500);
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
            <label>Think Mode Model</label>
            <p className="settings-hint">
              Used when the "Think" toggle is on in chat. Pick a reasoning model
              (e.g. qwen3, deepseek-r1). Falls back to the active chat model if unset.
            </p>
            <select
              value={thinkingModel}
              onChange={(e) => saveThinking(e.target.value)}
              className="settings-select"
            >
              <option value="">Same as chat model</option>
              {models.map((m) => (
                <option key={m.model_id} value={m.model_id}>
                  {m.display_name || m.model_id}
                </option>
              ))}
            </select>
            {thinkingStatus && <span className="settings-status">{thinkingStatus}</span>}
          </div>

          <div className="settings-group">
            <label>Persona</label>
            <p className="settings-hint">
              Customizes how the assistant responds in this field. Leave empty to
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
              <button className="action-btn" onClick={savePersona}>Save Persona</button>
              {personaStatus && <span className="settings-status">{personaStatus}</span>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
