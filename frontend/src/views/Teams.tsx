/*
 * Paliteams view (embedded in the main app).
 *
 * PARALLEL IMPLEMENTATION NOTICE: frontend/team.html is a self-contained,
 * zero-build copy of this feature served at /team for LAN guests on any
 * device. The two share one wire protocol — if you change message types,
 * token flow, headers, or reconnect behaviour here, mirror it there
 * (the contract is documented in the header comment of team.html).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useApp } from '../AppContext';

interface GuestInfo {
  token: string;
  display_name: string;
  query_count: number;
  connected_at: number;
  last_active: number;
}

// Keepalive ping cadence and reconnect budget shared by both client UIs.
const WS_HEARTBEAT_MS = 25000;
const WS_MAX_RECONNECT = 5;

interface ChatMsg {
  kind: 'me' | 'ai' | 'sys';
  text: string;
}

interface HostMsg {
  sender_type: string;
  sender_name: string;
  content: string;
  timestamp: number;
}

const b64decode = (raw: string): string => {
  const b = raw.replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(b);
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
};

function decodeInviteCode(code: string): { session_id: string; host_ip: string; port: number; token: string } {
  if (!code.startsWith('PALI-')) throw new Error('Code must start with PALI-');
  return JSON.parse(b64decode(code.slice(5)));
}

export default function Teams() {
  const { addToast } = useApp();
  const [tab, setTab] = useState<'host' | 'guest'>('host');

  // host state
  const [fields, setFields] = useState<string[]>([]);
  const [hostField, setHostField] = useState<string>('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [hostToken, setHostToken] = useState('');
  const [code, setCode] = useState('');
  const [guests, setGuests] = useState<GuestInfo[]>([]);
  const [hostMessages, setHostMessages] = useState<HostMsg[]>([]);
  const hostMsgCountRef = useRef(0);

  // guest state
  const [guestStatus, setGuestStatus] = useState('Not connected');
  const [guestStatusClass, setGuestStatusClass] = useState('teams-status-off');
  const [guestError, setGuestError] = useState('');
  const [guestKicked, setGuestKicked] = useState(false);
  const [joined, setJoined] = useState(false);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const [codeInput, setCodeInput] = useState('');
  const [nameInput, setNameInput] = useState('');

  const wsRef = useRef<WebSocket | null>(null);
  // Mirror of `joined` for use inside ws event handlers (state closures are
  // stale — they capture the value from the render handleJoin ran in).
  const joinedRef = useRef(false);
  // Guest-side keepalive ping timer; cleared on close/unmount.
  const heartbeatRef = useRef<number | null>(null);
  // False once the component unmounts — stops reconnect loops and pings.
  const aliveRef = useRef(true);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const setStatus = (text: string, cls: string) => {
    setGuestStatus(text);
    setGuestStatusClass(cls);
  };

  const appendMsg = useCallback((m: ChatMsg) => {
    setMessages((prev) => [...prev, m]);
  }, []);

  useEffect(() => {
    if (messagesRef.current) messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [messages]);

  useEffect(() => {
    api.fields.list().then((d) => {
      setFields(d.fields);
      setHostField(d.active_field || d.fields[0] || '');
    }).catch(() => {});
  }, []);

  // poll guest list + chat feed while a session is active
  useEffect(() => {
    if (!sessionId || !hostToken) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const d = await api.teams.guests(sessionId, hostToken);
        if (!cancelled && d.guests) setGuests(d.guests);
      } catch {}
      try {
        const d = await api.teams.messages(sessionId, hostToken, hostMsgCountRef.current);
        if (!cancelled && d.messages && d.messages.length) {
          hostMsgCountRef.current += d.messages.length;
          setHostMessages((prev) => [...prev, ...d.messages!]);
        }
      } catch {}
    };
    poll();
    const t = setInterval(poll, 3000);
    return () => { cancelled = true; clearInterval(t); };
  }, [sessionId, hostToken]);

  // close ws + stop heartbeat/reconnects on unmount
  useEffect(() => () => {
    aliveRef.current = false;
    if (heartbeatRef.current !== null) clearInterval(heartbeatRef.current);
    wsRef.current?.close();
  }, []);

  const handleCreate = async () => {
    if (!hostField) return;
    try {
      const d = await api.teams.create(hostField);
      if (d.error) { addToast(d.error); return; }
      if (d.code && d.session_id && d.host_token) {
        setSessionId(d.session_id);
        setHostToken(d.host_token);
        setCode(d.code);
        addToast('Share created — send the code to your guest');
      }
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Create failed');
    }
  };

  const handleInvite = async () => {
    if (!sessionId || !hostToken) return;
    try {
      const d = await api.teams.invite(sessionId, hostToken);
      if (d.error) { addToast(d.error); return; }
      if (d.code) setCode(d.code);
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Invite failed');
    }
  };

  const handleEnd = async () => {
    if (!sessionId || !hostToken) return;
    try {
      await api.teams.end(sessionId, hostToken);
      setSessionId(null);
      setHostToken('');
      setCode('');
      setGuests([]);
      setHostMessages([]);
      hostMsgCountRef.current = 0;
      addToast('Session ended');
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'End failed');
    }
  };

  const handleKick = async (token: string) => {
    if (!sessionId || !hostToken) return;
    await api.teams.kick(sessionId, token, hostToken);
  };

  const copyCode = () => {
    navigator.clipboard.writeText(code).catch(() => {});
    addToast('Code copied');
  };

  const handleJoin = () => {
    const name = nameInput.trim() || 'Guest';
    setGuestError('');
    setGuestKicked(false);
    let payload: { session_id: string; host_ip: string; port: number; token: string };
    try {
      payload = decodeInviteCode(codeInput.trim());
    } catch (e) {
      setGuestError(e instanceof Error ? e.message : 'Invalid invite code');
      return;
    }
    // Reconnect credential: prefer the session token minted at our first
    // successful join so refreshes/reconnects never re-burn the invite.
    const sessionKey = `paliteams_st_${payload.session_id}`;
    setStatus('Connecting...', 'teams-status-think');

    let attempts = 0;
    let kickedLocal = false;
    let joinRejected = false;

    const startHeartbeat = (ws: WebSocket) => {
      if (heartbeatRef.current !== null) clearInterval(heartbeatRef.current);
      heartbeatRef.current = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
      }, WS_HEARTBEAT_MS);
    };
    const stopHeartbeat = () => {
      if (heartbeatRef.current !== null) { clearInterval(heartbeatRef.current); heartbeatRef.current = null; }
    };

    const connectOnce = () => {
      if (!aliveRef.current || kickedLocal || joinRejected) return;
      const savedToken = localStorage.getItem(sessionKey);
      const credToken = savedToken || payload.token;
      const url = `ws://${payload.host_ip}:${payload.port}/ws/team/${payload.session_id}?token=${encodeURIComponent(credToken)}`;
      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
      } catch (e) {
        setGuestError('Failed to open connection');
        setStatus('Not connected', 'teams-status-off');
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'join', display_name: name, permission: 'query' }));
        startHeartbeat(ws);
      };
      ws.onmessage = (ev) => {
        let msg: { type: string; [k: string]: unknown };
        try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.type === 'joined') {
          joinedRef.current = true;
          attempts = 0;
          if (typeof msg.session_token === 'string' && msg.session_token) {
            try { localStorage.setItem(sessionKey, msg.session_token); } catch {}
          }
          setJoined(true);
          setStatus(`Connected to ${msg.field_name}`, 'teams-status-on');
          setMessages([]);
          appendMsg({ kind: 'sys', text: `Joined shared Palispace: ${msg.field_name}` });
        } else if (msg.type === 'kicked') {
          kickedLocal = true;
          joinedRef.current = false;
          stopHeartbeat();
          try { localStorage.removeItem(sessionKey); } catch {}
          setJoined(false);
          setGuestKicked(true);
          setStatus('Not connected', 'teams-status-off');
          ws.close();
        } else if (msg.type === 'stream_chunk') {
          const text = String(msg.text ?? '');
          setThinking(false);
          setStatus('Connected', 'teams-status-on');
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.kind === 'ai') {
              last.text += text;
            } else {
              next.push({ kind: 'ai', text });
            }
            return next;
          });
        } else if (msg.type === 'stream_end') {
          setThinking(false);
          setStatus('Connected', 'teams-status-on');
        } else if (msg.type === 'error') {
          setThinking(false);
          if (!joinedRef.current) {
            joinRejected = true;
            stopHeartbeat();
            setStatus('Not connected', 'teams-status-off');
            setGuestError(String(msg.message || 'Could not join'));
            ws.close();
          } else {
            setStatus('Connected', 'teams-status-on');
            appendMsg({ kind: 'ai', text: `(error) ${msg.message}` });
          }
        }
      };
      ws.onclose = () => {
        stopHeartbeat();
        // Kicked / rejected-at-join / unmounted: the right UI is already
        // showing — never override it or attempt reconnects.
        if (kickedLocal || joinRejected || !aliveRef.current) return;
        if (joinedRef.current) {
          joinedRef.current = false;
          setJoined(false);
          if (attempts < WS_MAX_RECONNECT) {
            attempts += 1;
            const delay = Math.min(15000, 1000 * 2 ** (attempts - 1));
            appendMsg({ kind: 'sys', text: `Connection lost — retrying in ${delay / 1000}s (${attempts}/${WS_MAX_RECONNECT})...` });
            setStatus(`Reconnecting in ${delay / 1000}s...`, 'teams-status-think');
            setTimeout(connectOnce, delay);
          } else {
            setStatus('Disconnected', 'teams-status-off');
            appendMsg({ kind: 'sys', text: 'Could not reconnect.' });
          }
        } else {
          setGuestError('Connection refused — is the host app running on the same network? Check its firewall settings.');
          setStatus('Not connected', 'teams-status-off');
        }
      };
    };

    connectOnce();
  };

  const handleSend = () => {
    const ws = wsRef.current;
    const text = input.trim();
    if (!ws || ws.readyState !== WebSocket.OPEN || !joined || !text) return;
    setInput('');
    appendMsg({ kind: 'me', text });
    setThinking(true);
    setStatus('Thinking...', 'teams-status-think');
    ws.send(JSON.stringify({ type: 'query', text }));
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  return (
    <div className="teams-view">
      <div className="teams-tabs">
        <button
          className={`teams-tab${tab === 'host' ? ' active' : ''}`}
          onClick={() => setTab('host')}
        >
          Host
        </button>
        <button
          className={`teams-tab${tab === 'guest' ? ' active' : ''}`}
          onClick={() => setTab('guest')}
        >
          Guest
        </button>
        <span className="teams-tabs-hint">Share a Palispace with another device on this network</span>
      </div>

      {tab === 'host' && (
        <div className="teams-pane">
          <div className="teams-card">
            <h3>Share this folder</h3>
            <select value={hostField} onChange={(e) => setHostField(e.target.value)}>
              {fields.map((f) => <option key={f} value={f}>{f}</option>)}
              {fields.length === 0 && <option value="">No fields — add one in PaliSpace first</option>}
            </select>
            <button className="teams-btn" onClick={handleCreate} disabled={!hostField}>
              Share this folder
            </button>
          </div>

          {sessionId && (
            <>
              <div className="teams-card">
                <h3>Active share</h3>
                <div className="teams-code" onClick={copyCode} title="Click to copy">{code}</div>
                <div className="teams-btn-row">
                  <button className="teams-btn teams-btn-ghost" onClick={copyCode}>Copy code</button>
                  <button className="teams-btn teams-btn-ghost" onClick={handleInvite}>New invite code</button>
                  <button className="teams-btn teams-btn-danger" onClick={handleEnd}>End session</button>
                </div>
              </div>

              <div className="teams-card">
                <h3>Connected guests</h3>
                {guests.length === 0 && <div className="teams-muted">No guests yet.</div>}
                {guests.map((g) => (
                  <div className="teams-guest-row" key={g.token}>
                    <div>
                      <div className="teams-guest-name">{g.display_name}</div>
                      <div className="teams-muted">{g.query_count} {g.query_count === 1 ? 'query' : 'queries'}</div>
                    </div>
                    <button className="teams-btn teams-btn-danger teams-btn-sm" onClick={() => handleKick(g.token)}>Kick</button>
                  </div>
                ))}
              </div>

              <div className="teams-card">
                <h3>Session chat</h3>
                {hostMessages.length === 0 && <div className="teams-muted">No messages yet.</div>}
                {hostMessages.map((m, i) => (
                  <div key={i} className={`teams-msg ${m.sender_type === 'guest' ? 'me' : 'ai'}`}>
                    <div>{m.content}</div>
                    <div className="teams-muted" style={{ fontSize: 11 }}>
                      {m.sender_type === 'guest' ? m.sender_name : 'AI'}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {tab === 'guest' && (
        <div className="teams-pane">
          {!joined ? (
            <div className="teams-card teams-join-card">
              <h3>Join a shared Palispace</h3>
              <div className={`teams-status ${guestStatusClass}`}>{guestStatus}</div>
              {guestKicked && <div className="teams-kicked">You were removed from this session.</div>}
              <label>Invite code</label>
              <input value={codeInput} onChange={(e) => setCodeInput(e.target.value)} placeholder="PALI-..." />
              <label>Display name</label>
              <input value={nameInput} onChange={(e) => setNameInput(e.target.value)} placeholder="e.g. Alice" />
              <button className="teams-btn" onClick={handleJoin} disabled={!codeInput.trim()}>Join</button>
              {guestError && <div className="teams-error">{guestError}</div>}
            </div>
          ) : (
            <div className="teams-chat">
              <div className="teams-chat-head">
                <div className={`teams-status ${guestStatusClass}`}>{guestStatus}</div>
              </div>
              <div className="teams-messages" ref={messagesRef}>
                {messages.map((m, i) => (
                  <div key={i} className={`teams-msg ${m.kind}`}>{m.text}</div>
                ))}
                {thinking && <div className="teams-msg ai teams-thinking">thinking...</div>}
              </div>
              <div className="teams-input-row">
                <input
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleSend(); }}
                  placeholder="Ask about the shared folder..."
                />
                <button className="teams-btn" onClick={handleSend} disabled={!input.trim()}>Send</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}