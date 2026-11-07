"""Thin, dependency-free web/mobile client for the local OpenAI-compatible API.

Served at ``GET /client``. The page is public (it is just HTML/CSS/JS), while
the API calls it makes still require the per-install bearer token. That keeps
the desktop app untouched and gives phones/tablets a usable chat surface on the
same LAN without shipping a second frontend.
"""

from __future__ import annotations

CLIENT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b0b0c">
<title>PaliMind</title>
<style>
  :root {
    --bg:#0b0b0c; --surface:#141416; --surface-2:#1c1c1f; --line:#2a2a2e;
    --ink:#f2f2f2; --muted:#9b9ba3; --inverse:#f2f2f2; --inverse-ink:#0b0b0c;
    --radius:14px; --font: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  @media (prefers-color-scheme: light) {
    :root { --bg:#f7f7f5; --surface:#ffffff; --surface-2:#efefec; --line:#dcdcd6;
      --ink:#111; --muted:#666; --inverse:#111; --inverse-ink:#fff; }
  }
  * { box-sizing:border-box; }
  html,body { height:100%; }
  body {
    margin:0; background:var(--bg); color:var(--ink); font-family:var(--font);
    display:flex; flex-direction:column; min-height:100dvh;
    padding: env(safe-area-inset-top) env(safe-area-inset-right)
             env(safe-area-inset-bottom) env(safe-area-inset-left);
  }
  header {
    display:flex; align-items:center; gap:10px; padding:12px 16px;
    border-bottom:1px solid var(--line); background:var(--surface);
  }
  header strong { font-weight:650; letter-spacing:-.01em; }
  header .dot { width:8px; height:8px; border-radius:99px; background:var(--muted); }
  header .dot.on { background:var(--ink); }
  #models {
    margin-left:auto; max-width:46vw; padding:6px 8px; border:1px solid var(--line);
    border-radius:9px; background:var(--surface-2); color:var(--ink); font:inherit; font-size:13px;
  }
  main { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:12px; }
  .msg { max-width:88%; padding:10px 13px; border-radius:var(--radius); line-height:1.5;
         white-space:pre-wrap; overflow-wrap:anywhere; font-size:15px; }
  .msg.user { align-self:flex-end; background:var(--inverse); color:var(--inverse-ink); border-bottom-right-radius:4px; }
  .msg.assistant { align-self:flex-start; background:var(--surface); border:1px solid var(--line); border-bottom-left-radius:4px; }
  .msg.error { align-self:center; background:transparent; border:1px solid var(--line); color:var(--muted); font-size:13px; }
  form {
    display:flex; gap:8px; align-items:flex-end; padding:12px 14px 18px;
    border-top:1px solid var(--line); background:var(--surface);
  }
  textarea {
    flex:1; min-height:44px; max-height:180px; resize:none; padding:11px 13px;
    border:1px solid var(--line); border-radius:12px; background:var(--surface-2);
    color:var(--ink); font:inherit; font-size:15px; line-height:1.4;
  }
  button {
    height:44px; padding:0 16px; border:none; border-radius:12px; cursor:pointer;
    background:var(--inverse); color:var(--inverse-ink); font:inherit; font-weight:650;
  }
  button:disabled { opacity:.4; cursor:default; }
  #auth {
    display:none; padding:18px; border:1px solid var(--line); border-radius:var(--radius);
    background:var(--surface); margin:16px; gap:10px; flex-direction:column;
  }
  #auth.show { display:flex; }
  #auth p { margin:0; color:var(--muted); font-size:13px; line-height:1.5; }
  #token { padding:10px 12px; border:1px solid var(--line); border-radius:10px;
           background:var(--surface-2); color:var(--ink); font:inherit; }
  @media (max-width:420px) { main { padding:12px; } .msg { max-width:94%; } }
</style>
</head>
<body>
<header>
  <span class="dot" id="status"></span>
  <strong>PaliMind</strong>
  <select id="models" aria-label="Model"></select>
</header>
<section id="auth">
  <p>Enter the local API token from <code>~/.palimind/api_token</code>. It is stored only in this browser.</p>
  <input id="token" type="password" autocomplete="off" placeholder="API token">
  <button id="save">Connect</button>
</section>
<main id="log" aria-live="polite"></main>
<form id="composer">
  <textarea id="input" rows="1" placeholder="Ask anything…" enterkeyhint="send"></textarea>
  <button id="send" type="submit">Send</button>
</form>
<script>
const log = document.getElementById('log');
const input = document.getElementById('input');
const send = document.getElementById('send');
const models = document.getElementById('models');
const auth = document.getElementById('auth');
const tokenInput = document.getElementById('token');
const statusDot = document.getElementById('status');
let messages = [];
let token = localStorage.getItem('palimind_token') || '';

function headers() {
  return { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token };
}
function bubble(role, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + role;
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}
function showAuth(show) { auth.classList.toggle('show', show); }
async function loadModels() {
  try {
    const res = await fetch('/v1/models', { headers: headers() });
    if (res.status === 401 || res.status === 403) { showAuth(true); return; }
    const data = await res.json();
    models.innerHTML = '';
    (data.data || []).forEach((m) => {
      const option = document.createElement('option');
      option.value = m.id; option.textContent = m.id;
      models.appendChild(option);
    });
    const saved = localStorage.getItem('palimind_model');
    if (saved && [...models.options].some((o) => o.value === saved)) models.value = saved;
    statusDot.classList.add('on');
    showAuth(false);
  } catch (e) {
    showAuth(true);
  }
}
document.getElementById('save').onclick = () => {
  token = tokenInput.value.trim();
  localStorage.setItem('palimind_token', token);
  loadModels();
};
models.onchange = () => localStorage.setItem('palimind_model', models.value);
input.addEventListener('input', () => {
  input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 180) + 'px';
});
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); document.getElementById('composer').requestSubmit(); }
});
document.getElementById('composer').onsubmit = async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || send.disabled) return;
  input.value = ''; input.style.height = 'auto';
  messages.push({ role: 'user', content: text });
  bubble('user', text);
  const answer = bubble('assistant', '…');
  send.disabled = true;
  try {
    const res = await fetch('/v1/chat/completions', {
      method: 'POST', headers: headers(),
      body: JSON.stringify({ model: models.value, messages, stream: false })
    });
    if (res.status === 401 || res.status === 403) { showAuth(true); answer.textContent = 'Token rejected.'; return; }
    const data = await res.json();
    const content = data?.choices?.[0]?.message?.content || data?.error || 'No response.';
    answer.textContent = content;
    messages.push({ role: 'assistant', content });
  } catch (err) {
    answer.className = 'msg error'; answer.textContent = 'Connection lost: ' + err.message;
  } finally {
    send.disabled = false; log.scrollTop = log.scrollHeight;
  }
};
if (token) { loadModels(); } else { showAuth(true); }
</script>
</body>
</html>
"""
