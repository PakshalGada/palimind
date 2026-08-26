import { useCallback, useEffect, useRef, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { api } from '../api';
import { formatMarkdown } from '../utils/markdown';
import type { GlanceSession, ModelItem, Recommendation } from '../types';
import './glance-workspace.css';

const IS_TAURI = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

function fmtTs(sec?: number): string {
  if (!sec) return '';
  return new Date(sec * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export default function PaliVisionWorkspace() {
  const [sessions, setSessions] = useState<GlanceSession[]>([]);
  const [active, setActive] = useState<GlanceSession | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(null);

  const [models, setModels] = useState<ModelItem[]>([]);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [currentModel, setCurrentModel] = useState('Loading...');
  const [ddOpen, setDdOpen] = useState(false);
  const [ddTab, setDdTab] = useState<'models' | 'cookbook'>('models');
  const [search, setSearch] = useState('');
  const [cookbookLoaded, setCookbookLoaded] = useState(false);

  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [lightbox, setLightbox] = useState(false);
  const [screenshotCollapsed, setScreenshotCollapsed] = useState(false);

  const msgsRef = useRef<HTMLDivElement | null>(null);

  const loadSessions = useCallback(async () => {
    try {
      const data = await api.palivision.sessions();
      setSessions(data.sessions || []);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    loadSessions();
    api.config.get().then((d) => { if (d.chat_model) setCurrentModel(d.chat_model); }).catch(() => {});
  }, [loadSessions]);

  const loadModels = useCallback(async () => {
    try {
      const data = await api.models.list();
      setModels(data.models ?? []);
      if (data.current_model) setCurrentModel(data.current_model);
    } catch {
      /* ignore */
    }
  }, []);

  const loadCookbook = useCallback(async () => {
    try {
      const data = await api.cookbook.recommendations(8);
      setRecs(data.recommendations ?? []);
    } catch {
      /* ignore */
    }
  }, []);

  const switchTab = (tab: 'models' | 'cookbook') => {
    setDdTab(tab);
    if (tab === 'models') loadModels();
    else if (!cookbookLoaded) {
      setCookbookLoaded(true);
      loadCookbook();
    }
  };

  const selectModel = (id: string) => {
    setCurrentModel(id);
    setDdOpen(false);
    api.config.setModel(id).catch(() => {});
  };

  const startCountdown = () => {
    if (countdown !== null) return;
    setCountdown(3);
  };

  useEffect(() => {
    if (countdown === null) return;
    if (countdown <= 0) {
      setCountdown(null);
      if (IS_TAURI) invoke('open_glance').catch(() => {});
      return;
    }
    const t = setTimeout(() => setCountdown((c) => (c === null ? null : c - 1)), 1000);
    return () => clearTimeout(t);
  }, [countdown]);

  const openSession = (sess: GlanceSession) => {
    setActive(sess);
    setScreenshotCollapsed(false);
    setStreaming('');
    setInput('');
    if (sess.chat_model) setCurrentModel(sess.chat_model);
  };

  const deleteSession = async (id: string) => {
    await api.palivision.deleteSession(id);
    setSessions((prev) => prev.filter((s) => s.id !== id));
    setActive((prev) => (prev?.id === id ? null : prev));
  };

  const send = async () => {
    if (!active || isBusy) return;
    const text = input.trim();
    if (!text) return;

    setInput('');
    setIsBusy(true);
    setStreaming('');
    const history = active.messages || [];
    let fullText = '';

    try {
      const res = await api.palivision.analyze({
        user_prompt: text,
        image_b64: active.screenshot_b64 || '',
        chat_model: currentModel,
        web_search: false,
        messages: history,
      });

      if (!res.ok || !res.body) throw new Error(`Server returned ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let done = false;

      while (!done) {
        const { done: d, value } = await reader.read();
        if (d) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data: ')) continue;
          const payload = trimmed.slice(6);
          if (payload === '[DONE]') { done = true; break; }
          try {
            const parsed = JSON.parse(payload);
            if (parsed.type === 'screen_context') continue;
            const token = parsed.token || '';
            if (token) {
              fullText += token;
              setStreaming(fullText);
            }
          } catch {
            /* ignore */
          }
        }
      }

      const updated: GlanceSession = {
        ...active,
        messages: [
          ...history,
          { role: 'user', content: text, ts: Date.now() },
          { role: 'assistant', content: fullText || '(No response from model)', ts: Date.now() },
        ],
      };
      setActive(updated);
      setSessions((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      setStreaming('');

      api.palivision
        .saveSession({
          session_id: updated.id,
          title: updated.title,
          messages: updated.messages,
          screen_summary: updated.screen_summary || '',
          chat_model: currentModel,
        })
        .catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      setStreaming(`Error: ${msg}`);
    } finally {
      setIsBusy(false);
    }
  };

  const filteredModels = search
    ? models.filter((m) => m.model_id.toLowerCase().includes(search.toLowerCase()))
    : models;

  return (
    <div className="glance-workspace active">
      <aside className={`glance-ws-sidebar${collapsed ? ' collapsed' : ''}`}>
        <div className="glance-ws-sidebar-header">
          <span className="glance-ws-sidebar-title">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" /></svg>
            Screen History
          </span>
          <div className="glance-ws-sidebar-actions">
            <button className="icon-btn" title="New Analysis" onClick={startCountdown}>
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
            </button>
            <button className="icon-btn" title="Toggle sidebar" onClick={() => setCollapsed((c) => !c)}>
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6" /></svg>
            </button>
          </div>
        </div>
        <div className="glance-ws-session-list">
          {sessions.length === 0 ? (
            <div className="glance-ws-empty">
              <p>No screen analyses yet.</p>
              <span>Press <kbd>Ctrl+Shift+V</kbd> to open PaliGlance.</span>
            </div>
          ) : (
            sessions.map((sess) => {
              const ts = fmtTs(sess.created_at);
              const msgCount = (sess.messages || []).length;
              const preview = (sess.messages || []).find((m) => m.role === 'user')?.content?.slice(0, 60) || 'Screen analysis';
              return (
                <div
                  key={sess.id}
                  className={`glance-ws-session-card${active?.id === sess.id ? ' active' : ''}`}
                  onClick={() => openSession(sess)}
                >
                  {sess.screenshot_b64 ? (
                    <img className="glance-ws-card-thumb" src={`data:image/png;base64,${sess.screenshot_b64}`} alt="Screenshot" />
                  ) : (
                    <div className="glance-ws-card-thumb--empty">
                      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="3" /><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" /></svg>
                    </div>
                  )}
                  <div className="glance-ws-card-body">
                    <div className="glance-ws-card-header">
                      <span className="glance-ws-card-title">{sess.title || `Screen — ${ts}`}</span>
                      {msgCount > 0 && <span className="glance-ws-card-badge">{msgCount}</span>}
                    </div>
                    <span className="glance-ws-card-preview">{preview}</span>
                    <span className="glance-ws-card-ts">{ts}</span>
                  </div>
                  <button
                    className="glance-ws-card-del"
                    title="Delete"
                    onClick={(e) => { e.stopPropagation(); deleteSession(sess.id); }}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
                  </button>
                </div>
              );
            })
          )}
        </div>
      </aside>

      <main className="glance-ws-main">
        {!active ? (
          <div className="glance-ws-welcome">
            <div className="glance-ws-welcome-inner">
              <svg width="48" height="48" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.25 }}><circle cx="12" cy="12" r="3" /><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" /></svg>
              <h2>PaliGlance</h2>
              <p>Point your AI at any screen, window, or app and ask questions about it.</p>
              <button className="glance-start-btn" onClick={startCountdown}>
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" /></svg>
                Start Analysis
              </button>
              <span className="glance-ws-welcome-hint">or press <kbd>Ctrl+Shift+V</kbd></span>
            </div>
          </div>
        ) : (
          <div className="glance-ws-convo">
            <div className={`glance-ws-screenshot-panel${screenshotCollapsed ? ' collapsed' : ''}`}>
              {active.screenshot_b64 && (
                <img
                  className="glance-ws-screenshot-thumb"
                  src={`data:image/png;base64,${active.screenshot_b64}`}
                  alt="Screen capture"
                  onClick={() => setLightbox(true)}
                />
              )}
              <div className="glance-ws-meta">
                {active.created_at && (
                  <span className="glance-meta-item">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
                    {new Date(active.created_at * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
                  </span>
                )}
                {active.ocr_text && (
                  <span className="glance-meta-item">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /></svg>
                    {active.ocr_text.slice(0, 80)}{active.ocr_text.length > 80 ? '…' : ''}
                  </span>
                )}
                <span className="glance-meta-item">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
                  {(active.messages || []).length} message{(active.messages || []).length !== 1 ? 's' : ''}
                </span>
              </div>
              <button className="icon-btn" title="Toggle screenshot" style={{ marginLeft: 'auto' }} onClick={() => setScreenshotCollapsed((c) => !c)}>
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="18 15 12 9 6 15" /></svg>
              </button>
            </div>

            <div className="glance-ws-messages" ref={msgsRef}>
              {(active.messages || []).map((m, i) => (
                <div key={i} className={`glance-ws-msg glance-ws-msg--${m.role}`}>
                  {m.role === 'assistant' ? (
                    <span dangerouslySetInnerHTML={{ __html: formatMarkdown(m.content) }} />
                  ) : (
                    escapeHtml(m.content)
                  )}
                </div>
              ))}
              {streaming && (
                <div className="glance-ws-msg glance-ws-msg--assistant streaming">
                  <span dangerouslySetInnerHTML={{ __html: formatMarkdown(streaming) }} />
                </div>
              )}
            </div>

            <div className="glance-ws-input-wrapper">
              <div className="glance-ws-input-bar">
                <textarea
                  placeholder="Continue this analysis…"
                  rows={1}
                  value={input}
                  disabled={isBusy}
                  onChange={(e) => {
                    setInput(e.target.value);
                    e.target.style.height = 'auto';
                    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
                  }}
                />
                <button className="glance-ws-send-btn" title="Send" disabled={isBusy} onClick={send}>
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="19" x2="12" y2="5" /><polyline points="5 12 12 5 19 12" /></svg>
                </button>
              </div>
              <div className="glance-ws-input-footer">
                <div className="glance-ws-model-area">
                  <button className="glance-ws-model-pill" type="button" onClick={(e) => { e.stopPropagation(); setDdOpen((v) => !v); }}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
                    <span className="glance-ws-model-name">{currentModel}</span>
                    <svg xmlns="http://www.w3.org/2000/svg" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="6 9 12 15 18 9" /></svg>
                  </button>
                  {ddOpen && (
                    <div className="glance-ws-model-dropdown">
                      <div className="ms-tab-bar" role="tablist">
                        <button className={`ms-tab${ddTab === 'models' ? ' active' : ''}`} onClick={() => switchTab('models')}>Models</button>
                        <button className={`ms-tab${ddTab === 'cookbook' ? ' active' : ''}`} onClick={() => switchTab('cookbook')}>Cookbook</button>
                      </div>
                      {ddTab === 'models' ? (
                        <div className="ms-panel">
                          <div className="model-search-container">
                            <input type="text" className="model-search-input" placeholder="Search models..." autoComplete="off" value={search} onChange={(e) => setSearch(e.target.value)} />
                          </div>
                          <div className="model-list" role="listbox">
                            {filteredModels.length === 0 ? (
                              <div className="model-list-loading">{models.length === 0 ? 'Fetching models…' : 'No match'}</div>
                            ) : (
                              filteredModels.map((m) => (
                                <div key={m.model_id} className={`model-list-item${m.model_id === currentModel ? ' active-model' : ''}`} onClick={() => selectModel(m.model_id)}>
                                  <span className="model-list-item-name">{m.display_name || m.model_id}</span>
                                  <span className="model-list-item-meta">{m.parameter_size || ''} {m.size_gb ? m.size_gb + 'GB' : ''}</span>
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                      ) : (
                        <div className="ms-panel">
                          <div className="ms-rec-header"><span className="ms-rec-title">Recommended for your hardware</span></div>
                          <div className="rec-grid">
                            {recs.length === 0 ? (
                              <span className="model-menu-state">Loading…</span>
                            ) : (
                              recs.map((rec) => (
                                <div key={rec.name} className={`rec-card${rec.name === currentModel ? ' recommended' : ''}`} onClick={() => selectModel(rec.name)}>
                                  <span className="rec-name">{rec.name}</span>
                                  <span className="rec-meta">{rec.params_b}B · {rec.fit}</span>
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </main>

      {countdown !== null && (
        <div className="glance-countdown-overlay">
          <div className="glance-countdown-modal">
            <div className="glance-countdown-number" key={countdown}>{countdown}</div>
            <p className="glance-countdown-label">Select or focus the screen or window you want PaliGlance to analyze</p>
          </div>
        </div>
      )}

      {lightbox && active?.screenshot_b64 && (
        <div className="glance-lightbox" onClick={() => setLightbox(false)}>
          <div className="glance-lightbox-inner">
            <img src={`data:image/png;base64,${active.screenshot_b64}`} alt="Screenshot" />
            <button className="glance-lightbox-close" aria-label="Close">×</button>
          </div>
        </div>
      )}
    </div>
  );
}
