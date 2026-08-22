import { useCallback, useEffect, useRef, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { api } from '../api';
import { formatMarkdown } from '../utils/markdown';
import type { GlanceMessage, ModelItem, Recommendation } from '../types';

interface RenderMsg {
  role: 'user' | 'assistant';
  content: string;
}

function generateSessionId(): string {
  return 'glance_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
}

const IS_TAURI = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

function buildHistory(messages: RenderMsg[]): GlanceMessage[] {
  return messages
    .filter((m) => m.content.trim().length > 0)
    .map((m, i) => ({ role: m.role, content: m.content, ts: Date.now() - (messages.length - i) }));
}

export default function GlanceApp() {
  const [messages, setMessages] = useState<RenderMsg[]>([]);
  const [input, setInput] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [screenshotB64, setScreenshotB64] = useState<string | null>(null);
  const [status, setStatus] = useState<'captured' | 'capturing' | 'none'>('none');
  const [activeModel, setActiveModel] = useState('Loading...');

  const [models, setModels] = useState<ModelItem[]>([]);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [ddOpen, setDdOpen] = useState(false);
  const [ddTab, setDdTab] = useState<'models' | 'cookbook'>('models');
  const [search, setSearch] = useState('');
  const [cookbookLoaded, setCookbookLoaded] = useState(false);

  const sessionIdRef = useRef(generateSessionId());
  const messagesRef = useRef<RenderMsg[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const streamRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const focusInput = () => textareaRef.current?.focus();

  const fetchActiveModel = useCallback(async () => {
    try {
      const data = await api.config.get();
      if (data.chat_model) setActiveModel(data.chat_model);
    } catch {
      /* ignore */
    }
  }, []);

  const resetForShow = useCallback(() => {
    sessionIdRef.current = generateSessionId();
    setMessages([]);
    messagesRef.current = [];
    setScreenshotB64(null);
    setStatus('capturing');
    setInput('');
    setCookbookLoaded(false);
    fetchActiveModel();
  }, [fetchActiveModel]);

  useEffect(() => {
    fetchActiveModel();

    if (!IS_TAURI) return;

    const unsubScreenshot = listen<string>('glance:screenshot', (event) => {
      const payload = event.payload ?? '';
      const b64 = payload.startsWith('data:image')
        ? payload.split(',')[1] ?? ''
        : payload;
      setScreenshotB64(b64 || null);
      setStatus(b64 ? 'captured' : 'none');
    });

    const unsubShown = listen('glance:shown', () => {
      resetForShow();
      focusInput();
    });

    return () => {
      unsubScreenshot.then((f) => f());
      unsubShown.then((f) => f());
    };
  }, [fetchActiveModel, resetForShow]);

  const hide = () => {
    if (IS_TAURI) {
      getCurrentWindow().hide().catch(() => {});
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') hide();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const loadModels = useCallback(async () => {
    try {
      const data = await api.models.list();
      setModels(data.models ?? []);
      if (data.current_model) setActiveModel(data.current_model);
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

  const openDropdown = () => {
    setDdOpen((v) => !v);
  };

  const switchTab = (tab: 'models' | 'cookbook') => {
    setDdTab(tab);
    if (tab === 'models') {
      loadModels();
    } else {
      if (!cookbookLoaded) {
        setCookbookLoaded(true);
        loadCookbook();
      }
    }
  };

  const selectModel = (id: string) => {
    setActiveModel(id);
    setDdOpen(false);
    api.config.setModel(id).catch(() => {});
  };

  const sendQuery = async () => {
    if (isBusy) return;
    const text = input.trim();
    if (!text) return;

    setInput('');
    setIsBusy(true);
    const userMsg: RenderMsg = { role: 'user', content: text };
    const next = [...messagesRef.current, userMsg];
    setMessages(next);
    messagesRef.current = next;

    let fullText = '';
    let screenCtx = '';

    try {
      const res = await api.palivision.analyze({
        user_prompt: text,
        image_b64: screenshotB64 || '',
        chat_model: activeModel,
        web_search: false,
        messages: buildHistory(next.filter((m) => m !== userMsg)),
      });

      if (!res.ok || !res.body) {
        throw new Error(`Server returned ${res.status}`);
      }

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
          if (payload === '[DONE]') {
            done = true;
            break;
          }
          try {
            const parsed = JSON.parse(payload);
            if (parsed.type === 'screen_context') {
              screenCtx = parsed.summary || '';
              continue;
            }
            const token = parsed.token || '';
            if (token) fullText += token;
          } catch {
            /* ignore malformed */
          }
          const streaming: RenderMsg[] = [
            ...next,
            { role: 'assistant', content: fullText },
          ];
          setMessages(streaming);
        }
      }

      const finalText = fullText || '(No response. Is Ollama running?)';
      const final: RenderMsg[] = [...next, { role: 'assistant', content: finalText }];
      setMessages(final);
      messagesRef.current = final;

      if (fullText) {
        const history = buildHistory(final);
        api.palivision
          .saveSession({
            session_id: sessionIdRef.current,
            title: `Screen — ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`,
            messages: history,
            screen_summary: screenCtx,
            screenshot_b64: screenshotB64 || '',
            ocr_text: screenCtx,
            chat_model: activeModel,
          })
          .catch(() => {});

        if (fullText.length > 50) {
          api.palivision
            .updateMemory({
              session_id: sessionIdRef.current,
              user_message: text,
              assistant_message: fullText,
              screen_summary: screenCtx,
            })
            .catch(() => {});
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      const final: RenderMsg[] = [...next, { role: 'assistant', content: `Error: ${msg}` }];
      setMessages(final);
      messagesRef.current = final;
    } finally {
      setIsBusy(false);
      focusInput();
    }
  };

  const filteredModels = search
    ? models.filter((m) => m.model_id.toLowerCase().includes(search.toLowerCase()))
    : models;

  return (
    <div className="glance-shell">
      <div className="glance-header">
        <div className="glance-title">
          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" />
          </svg>
          <span>PaliGlance</span>
        </div>
        <div className="glance-status">
          <span className={`glance-dot${status === 'captured' ? ' captured' : ''}`} title="Screenshot status" />
          <span className="glance-status-label">
            {status === 'captured' ? 'Screen captured' : status === 'capturing' ? 'Capturing…' : 'No capture'}
          </span>
        </div>
      </div>

      <div className="glance-messages" ref={streamRef}>
        {messages.length === 0 && (
          <div className="glance-empty">
            <p>Ask anything about your screen.</p>
            <span className="glance-hint">Press <kbd>Esc</kbd> to dismiss</span>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`glance-msg glance-msg-${m.role}`}>
            {m.role === 'assistant' ? (
              <div dangerouslySetInnerHTML={{ __html: formatMarkdown(m.content) || '<span class="glance-thinking">Analyzing screen…</span>' }} />
            ) : (
              m.content
            )}
          </div>
        ))}
      </div>

      <div className="glance-input-wrapper">
        <div className="glance-input-bar">
          <textarea
            id="glance-input"
            ref={textareaRef}
            placeholder="Ask about your screen…"
            rows={1}
            value={input}
            disabled={isBusy}
            onChange={(e) => {
              setInput(e.target.value);
              e.target.style.height = 'auto';
              e.target.style.height = Math.min(e.target.scrollHeight, 100) + 'px';
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendQuery();
              }
            }}
          />
          <button id="glance-send-btn" title="Send" aria-label="Send" disabled={isBusy} onClick={sendQuery}>
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="19" x2="12" y2="5" />
              <polyline points="5 12 12 5 19 12" />
            </svg>
          </button>
        </div>
        <div className="glance-input-footer">
          <div id="glance-model-area" className="glance-model-area">
            <button id="glance-model-btn" className="glance-model-pill glance-model-pill--btn" type="button" onClick={(e) => { e.stopPropagation(); openDropdown(); }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
              </svg>
              <span id="glance-model-name">{activeModel}</span>
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
            {ddOpen && (
              <div id="glance-model-dropdown" className="glance-model-dropdown">
                <div className="glance-ms-tab-bar">
                  <button className={`glance-ms-tab${ddTab === 'models' ? ' active' : ''}`} onClick={() => switchTab('models')}>Models</button>
                  <button className={`glance-ms-tab${ddTab === 'cookbook' ? ' active' : ''}`} onClick={() => switchTab('cookbook')}>Cookbook</button>
                </div>
                {ddTab === 'models' ? (
                  <div id="glance-ms-models" className="glance-ms-panel">
                    <input
                      type="text"
                      className="glance-model-search"
                      placeholder="Search models..."
                      autoComplete="off"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                    <div className="glance-model-list">
                      {filteredModels.length === 0 ? (
                        <span className="glance-loading">{models.length === 0 ? 'Fetching models…' : 'No match'}</span>
                      ) : (
                        filteredModels.map((m) => (
                          <div
                            key={m.model_id}
                            className={`glance-model-item${m.model_id === activeModel ? ' active' : ''}`}
                            onClick={() => selectModel(m.model_id)}
                          >
                            <span className="glance-model-item-name">{m.display_name || m.model_id}</span>
                            <span className="glance-model-item-meta">
                              {m.parameter_size || ''} {m.size_gb ? m.size_gb + 'GB' : ''}
                            </span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                ) : (
                  <div id="glance-ms-cookbook" className="glance-ms-panel">
                    <div className="glance-cookbook-list">
                      {recs.length === 0 ? (
                        <span className="glance-loading">Loading recommendations…</span>
                      ) : (
                        recs.map((rec) => (
                          <div
                            key={rec.name}
                            className={`glance-rec-card${rec.name === activeModel ? ' selected' : ''}`}
                            onClick={() => selectModel(rec.name)}
                          >
                            <span className="glance-rec-name">{rec.name}</span>
                            <span className="glance-rec-size">{rec.params_b}B · {rec.fit}</span>
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
  );
}
