"""Local observability endpoints and a tiny self-contained dashboard."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from palimind import metrics

router = APIRouter(tags=["metrics"])

_DASHBOARD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>PaliMind Metrics</title>
<style>
:root{color-scheme:dark;--bg:#0b0b0c;--panel:#141416;--line:#2a2a2d;--ink:#f2f2f2;--muted:#9a9aa2}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
header{padding:20px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:baseline}
h1{font-size:18px;margin:0;letter-spacing:.04em}
main{padding:20px 24px;display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
h2{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin:0 0 10px}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:4px 0;border-bottom:1px solid #1d1d20;vertical-align:top}
th{color:var(--muted);font-weight:400}td:last-child,th:last-child{text-align:right}
code{color:#fff}.muted{color:var(--muted)}#error{color:#ff9c9c;padding:8px 24px;display:none}
</style></head><body>
<header><h1>PALIMIND / METRICS</h1><span class="muted" id="stamp">loading…</span></header>
<div id="error"></div>
<main>
<section><h2>Requests</h2><div id="requests"></div></section>
<section><h2>Tokens</h2><div id="tokens"></div></section>
<section><h2>Tools</h2><div id="tools"></div></section>
<section><h2>Agent runs</h2><div id="agents"></div></section>
<section><h2>Indexing</h2><div id="index"></div></section>
<section><h2>Queue</h2><div id="queue"></div></section>
</main>
<script>
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function rows(obj){return '<table>'+Object.entries(obj||{}).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(typeof v==='object'?JSON.stringify(v):v)}</td></tr>`).join('')+'</table>'}
async function tick(){
  try{
    const r=await fetch('/metrics/data',{cache:'no-store'});
    if(!r.ok) throw new Error('HTTP '+r.status);
    const m=await r.json();
    document.getElementById('stamp').textContent='uptime '+m.uptime_s+'s · local-only';
    document.getElementById('requests').innerHTML='<p><code>'+m.requests.total+'</code> total</p>'+rows(m.requests.by_status)+rows(Object.fromEntries(Object.entries(m.requests.by_route).map(([k,v])=>[k,v.count+' · avg '+v.avg_ms+'ms · p95 '+v.p95_ms+'ms'])));
    document.getElementById('tokens').innerHTML='<p><code>'+m.tokens.total+'</code> tokens</p>'+rows(m.tokens.by_model);
    document.getElementById('tools').innerHTML=rows(Object.fromEntries(Object.entries(m.tools).map(([k,v])=>[k,v.success+' ok / '+v.failure+' fail · avg '+v.avg_ms+'ms'])));
    document.getElementById('agents').innerHTML=rows(m.agent_runs);
    document.getElementById('index').innerHTML=rows(m.index);
    document.getElementById('queue').innerHTML=rows({task_board_active:m.queue.task_board_active,...m.queue.jobs});
    document.getElementById('error').style.display='none';
  }catch(e){const el=document.getElementById('error');el.style.display='block';el.textContent='Metrics unavailable: '+e.message}
}
tick(); setInterval(tick,2000);
</script></body></html>"""


@router.get("/api/metrics")
async def get_metrics():
    """Local-only metrics snapshot (never sent anywhere)."""
    return metrics.snapshot()


@router.get("/metrics/data")
async def metrics_data():
    """Public loopback-only data source for the local dashboard."""
    return metrics.snapshot()


@router.get("/metrics", response_class=HTMLResponse)
async def metrics_dashboard():
    return HTMLResponse(_DASHBOARD)
