/**
 * PaliMind Email Workspace  –  email.js
 */
"use strict";

const EMAIL = {
  accounts: [], activeAccount: null, activeFolder: "inbox",
  emails: [], selectedEmail: null, searchDebounce: null,
  searchQuery: "", sortBy: "date", page: 0, loading: false,
  composeReplyId: null,
};

/* ── Avatar colours (deterministic by initial) ─────── */
const AVATAR_COLORS = [
  ["#1a1a2e","#7c3aed"],["#0d1b2a","#2563eb"],["#0f2417","#16a34a"],
  ["#2a1a1a","#dc2626"],["#1a1a0f","#ca8a04"],["#1a0f1a","#9333ea"],
  ["#0f1a1a","#0891b2"],["#1a1505","#d97706"],
];
function avatarColors(name) {
  const i = (name||"?").charCodeAt(0) % AVATAR_COLORS.length;
  return AVATAR_COLORS[i];
}

/* ── Bootstrap ─────────────────────────────────────── */
async function initEmailWorkspace() {
  renderEmailSkeleton();
  await Promise.all([loadEmailAccounts(), loadFolderBadges()]);
  await loadEmailList(true);
}

/* ── Accounts ──────────────────────────────────────── */
async function loadEmailAccounts() {
  try {
    const r = await fetch("/api/email/accounts");
    const d = await r.json();
    EMAIL.accounts = d.accounts || [];
  } catch (_) { EMAIL.accounts = []; }
  const sel = document.getElementById("email-account-sel");
  if (!sel) return;
  sel.innerHTML = '<option value="">All accounts</option>';
  EMAIL.accounts.forEach(a => {
    const o = document.createElement("option");
    o.value = a.label; o.textContent = a.email;
    sel.appendChild(o);
  });
}

/* ── Folder badges ─────────────────────────────────── */
async function loadFolderBadges() {
  try {
    const r = await fetch("/api/email/folders");
    const d = await r.json();
    (d.folders||[]).forEach(f => {
      const el = document.querySelector(`[data-folder-badge="${f.id}"]`);
      if (!el) return;
      el.textContent = f.count > 0 ? f.count : "";
      el.classList.toggle("has-count", f.count > 0);
    });
  } catch (_) {}
}

/* ── Skeleton loader ───────────────────────────────── */
function renderEmailSkeleton() {
  const list = document.getElementById("email-list-scroll");
  if (!list) return;
  list.innerHTML = Array(8).fill(0).map(() => `
    <div class="email-card" style="pointer-events:none">
      <div class="email-card-top">
        <div class="email-avatar" style="background:var(--border-color)"></div>
        <div class="email-card-meta">
          <div class="esk" style="width:80px;height:10px;margin-bottom:4px"></div>
          <div class="esk" style="width:40px;height:8px"></div>
        </div>
        <div class="esk" style="width:32px;height:8px"></div>
      </div>
      <div class="esk" style="width:90%;height:10px;margin-top:6px"></div>
      <div class="esk" style="width:70%;height:8px;margin-top:4px"></div>
    </div>
  `).join("");
}

/* ── Email list ────────────────────────────────────── */
async function loadEmailList(reset = true) {
  if (EMAIL.loading) return;
  EMAIL.loading = true;
  if (reset) { EMAIL.page = 0; renderEmailSkeleton(); }

  // update list title
  const labels = {
    inbox:"Inbox",unread:"Unread",needs_reply:"Needs Reply",
    today:"Today",sent:"Sent",drafts:"Drafts",spam:"Spam",
    newsletters:"Newsletters",archive:"Archive",
  };
  const titleEl = document.getElementById("email-list-title");
  if (titleEl) titleEl.textContent = labels[EMAIL.activeFolder] || EMAIL.activeFolder;

  try {
    let emails;
    if (EMAIL.searchQuery) {
      const r = await fetch(`/api/email/search?q=${encodeURIComponent(EMAIL.searchQuery)}&limit=80`);
      const d = await r.json();
      emails = (d.results||[]).map(x => ({
        id:x.email_id, subject:x.subject||"(no subject)",
        sender:x.sender||"", sender_name:x.sender_name||x.sender||"",
        date:x.date||0, summary:x.snippet||"", is_read:true,
        priority:0, spam_score:0, has_attachments:false,
      }));
    } else {
      const p = new URLSearchParams({
        folder:EMAIL.activeFolder, limit:60,
        offset:EMAIL.page*60, sort:EMAIL.sortBy,
      });
      if (EMAIL.activeAccount) p.set("account_label", EMAIL.activeAccount);
      const r = await fetch(`/api/email/list?${p}`);
      const d = await r.json();
      emails = d.emails || [];
    }

    if (reset) EMAIL.emails = emails;
    else EMAIL.emails.push(...emails);
    renderEmailList();
  } catch(e) {
    const list = document.getElementById("email-list-scroll");
    if (list) list.innerHTML = `<div class="email-empty">⚠ ${e.message}</div>`;
  } finally {
    EMAIL.loading = false;
  }
}

function renderEmailList() {
  const list = document.getElementById("email-list-scroll");
  if (!list) return;
  if (!EMAIL.emails.length) {
    list.innerHTML = '<div class="email-empty">No emails in this folder.</div>';
    return;
  }
  list.innerHTML = "";
  EMAIL.emails.forEach(em => list.appendChild(buildEmailCard(em)));
}

function buildEmailCard(em) {
  const card = document.createElement("div");
  card.className = `email-card${!em.is_read ? " unread" : ""}${EMAIL.selectedEmail?.id===em.id ? " active" : ""}`;
  card.dataset.emailId = em.id;

  const name = em.sender_name || em.sender || "?";
  const initials = name.slice(0,2).toUpperCase();
  const [bgC, fgC] = avatarColors(name);
  const dateStr = fmtDate(em.date);
  const pri = em.priority || 0;

  const badges = [];
  if (pri >= 80) badges.push(`<span class="email-icon-badge priority-high">🔴 urgent</span>`);
  else if (pri >= 60) badges.push(`<span class="email-icon-badge priority-med">🟡 high</span>`);
  if ((em.spam_score||0) >= 70) badges.push(`<span class="email-icon-badge spam-flag">⚠ spam?</span>`);
  if (em.has_attachments) badges.push(`<span class="email-icon-badge attachment">📎</span>`);

  card.innerHTML = `
    ${!em.is_read ? '<div class="email-unread-dot"></div>' : ""}
    <div class="email-card-top">
      <div class="email-avatar" style="background:${bgC};color:${fgC}">${initials}</div>
      <div class="email-card-meta">
        <div class="email-card-sender">${esc(name)}</div>
      </div>
      <div class="email-card-time">${dateStr}</div>
    </div>
    <div class="email-card-subject">${esc(em.subject)}</div>
    ${em.summary ? `<div class="email-card-preview">${esc(em.summary)}</div>` : ""}
    ${badges.length ? `<div class="email-card-icons">${badges.join("")}</div>` : ""}
  `;
  card.addEventListener("click", () => openEmail(em.id));
  return card;
}

/* ── Open email ────────────────────────────────────── */
async function openEmail(id) {
  document.querySelectorAll(".email-card").forEach(c =>
    c.classList.toggle("active", c.dataset.emailId == id)
  );
  const empty  = document.getElementById("email-viewer-empty");
  const viewer = document.getElementById("email-viewer-main");
  if (empty)  empty.style.display = "none";
  if (viewer) {
    viewer.classList.add("active");
    document.getElementById("email-viewer-body-text").textContent = "";
    document.getElementById("email-viewer-body-text").classList.add("loading-shimmer");
  }
  try {
    const r = await fetch(`/api/email/read/${id}`);
    const em = await r.json();
    if (em.error) throw new Error(em.error);
    EMAIL.selectedEmail = em;
    // remove unread dot from card
    const card = document.querySelector(`[data-email-id="${id}"]`);
    if (card) { card.classList.remove("unread"); card.querySelector(".email-unread-dot")?.remove(); }
    renderViewer(em);
    renderAISidebar(em);
  } catch(e) { toast("Failed to load email: "+e.message, "error"); }
}

function renderViewer(em) {
  const s = (id,v) => { const el=document.getElementById(id); if(el) el.innerHTML=v; };
  s("email-viewer-subject", esc(em.subject));
  s("email-viewer-from", `From: <span>${esc(em.sender_name||em.sender)}</span> &lt;${esc(em.sender)}&gt;`);
  s("email-viewer-to",   `To: <span>${esc(em.recipients||"")}</span>`);
  const ccEl = document.getElementById("email-viewer-cc");
  if (ccEl) { ccEl.style.display = em.cc ? "" : "none"; ccEl.innerHTML = em.cc ? `CC: <span>${esc(em.cc)}</span>` : ""; }
  const dateEl = document.getElementById("email-viewer-date");
  if (dateEl) dateEl.textContent = em.date ? new Date(em.date*1000).toLocaleString() : "";
  const bodyEl = document.getElementById("email-viewer-body-text");
  if (bodyEl) { bodyEl.classList.remove("loading-shimmer"); bodyEl.textContent = em.body_text||"(no body)"; }
  const attEl = document.getElementById("email-viewer-attachments");
  if (attEl) {
    if (em.attachments?.length) {
      attEl.innerHTML = em.attachments.map(a=>`<div class="attachment-chip">📎 ${esc(a.filename)} <span>(${fmtBytes(a.size_bytes)})</span></div>`).join("");
      attEl.style.display = "flex";
    } else { attEl.style.display = "none"; }
  }
}

function renderAISidebar(em) {
  const p2 = em.p2_meta||{};
  const s = (id,v) => { const el=document.getElementById(id); if(el) el.innerHTML=v||'<span style="color:var(--text-muted)">—</span>'; };
  s("ai-summary",       esc(em.summary||""));
  s("ai-priority-exp",  em.priority ? `Score: ${em.priority}/100` : "");
  s("ai-tags",          em.tags ? em.tags.split(",").map(t=>`<span class="email-icon-badge">${esc(t.trim())}</span>`).join(" ") : "");
  s("ai-needs-reply",   p2.needs_reply ? `<span class="email-icon-badge priority-high">Reply needed</span> ${esc(p2.reply_reason||"")}` : "No reply needed");
  s("ai-spam",          (p2.spam_status && p2.spam_status!=="safe") ? `<span class="email-icon-badge spam-flag">${esc(p2.spam_status)}</span> ${esc(p2.spam_reason||"")}` : "Clean");
  s("ai-suggested-reply","AI reply available – click Insert below.");
  const btn = document.getElementById("ai-insert-reply-btn");
  if (btn) btn.dataset.emailId = em.id;
}

/* ── Compose ───────────────────────────────────────── */
function openCompose(replyTo=null) {
  EMAIL.composeReplyId = replyTo?.id||null;
  document.getElementById("compose-modal-overlay")?.classList.add("open");
  document.getElementById("compose-modal-title").textContent = replyTo ? `Re: ${replyTo.subject}` : "New Message";
  document.getElementById("compose-to").value      = replyTo?.sender||"";
  document.getElementById("compose-cc").value      = "";
  document.getElementById("compose-subject").value = replyTo ? `Re: ${replyTo.subject}` : "";
  document.getElementById("compose-body").value    = "";
}
function closeCompose() { document.getElementById("compose-modal-overlay")?.classList.remove("open"); }

async function sendCompose() {
  const body = document.getElementById("compose-body").value.trim();
  if (!body) { toast("Body is empty.","error"); return; }
  try {
    if (EMAIL.composeReplyId) {
      const r = await fetch("/api/email/reply",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({email_id:EMAIL.composeReplyId,body,dry_run:false})});
      const d = await r.json(); if(d.error) throw new Error(d.error);
    } else {
      const to = document.getElementById("compose-to").value.trim();
      if (!to) { toast("Recipient required.","error"); return; }
      const acct = EMAIL.accounts[0]?.label;
      if (!acct) { toast("No account configured.","error"); return; }
      const r = await fetch("/api/email/compose",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({account_label:acct,to:[to],
          subject:document.getElementById("compose-subject").value.trim(),body})});
      const d = await r.json(); if(d.error) throw new Error(d.error);
    }
    closeCompose(); toast("Sent!","success");
  } catch(e) { toast("Send failed: "+e.message,"error"); }
}

async function aiDraftCompose() {
  const intent = prompt("Describe what you want to write:");
  if (!intent) return;
  toast("Generating draft…","info");
  try {
    const r = await fetch("/api/email/ai/draft",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({intent,recipient:document.getElementById("compose-to").value.trim(),
        email_id:EMAIL.composeReplyId})});
    const d = await r.json();
    if (d.draft) { document.getElementById("compose-body").value=d.draft; toast("Draft ready!","success"); }
  } catch(e) { toast("Draft failed: "+e.message,"error"); }
}

/* ── Actions ───────────────────────────────────────── */
async function archiveEmail(id) {
  await fetch("/api/email/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email_id:id})});
  EMAIL.emails = EMAIL.emails.filter(e=>e.id!==id);
  if (EMAIL.selectedEmail?.id===id) {
    EMAIL.selectedEmail=null;
    document.getElementById("email-viewer-main")?.classList.remove("active");
    document.getElementById("email-viewer-empty").style.display="flex";
  }
  renderEmailList(); toast("Archived.","success");
}
async function markEmailRead(id, isRead) {
  await fetch(isRead?"/api/email/mark_read":"/api/email/mark_unread",{method:"POST",
    headers:{"Content-Type":"application/json"},body:JSON.stringify({email_id:id})});
  const em=EMAIL.emails.find(e=>e.id===id); if(em) em.is_read=isRead;
  renderEmailList(); toast(isRead?"Marked read.":"Marked unread.","info");
}
async function reminderPrompt(id) {
  const due = prompt("Remind when? (e.g. tomorrow / 2026-06-20):");
  if (!due) return;
  const r = await fetch("/api/email/reminders",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({email_id:id,due,auto_note:true})});
  const d=await r.json(); d.error ? toast(d.error,"error") : toast("Reminder set!","success");
}

/* ── Sync ──────────────────────────────────────────── */
async function syncEmail() {
  if (!EMAIL.accounts.length) { toast("No accounts configured.","info"); return; }
  const btn=document.getElementById("email-sync-btn"); if(btn) btn.textContent="Syncing…";
  try {
    for (const a of EMAIL.accounts) {
      await fetch("/api/email/sync",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({account_label:a.label,limit:50,run_ai:true})});
    }
    toast("Sync complete!","success");
    await loadFolderBadges(); await loadEmailList();
  } catch(e) { toast("Sync error: "+e.message,"error"); }
  finally { if(btn) btn.textContent="Sync"; }
}

/* ── Ask inbox ─────────────────────────────────────── */
async function askInbox() {
  const inp=document.getElementById("inbox-chat-input"); if(!inp) return;
  const q=inp.value.trim(); if(!q) return;
  const res=document.getElementById("inbox-chat-result");
  if(res){res.textContent="Thinking…";res.classList.add("visible");}
  try {
    const r=await fetch("/api/email/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:q})});
    const d=await r.json();
    if(res){
      res.textContent=d.answer||d.error||"No answer.";
      if(d.citations?.length) res.textContent+="\n\nSources:"+d.citations.map(c=>`\n• [#${c.id}] ${c.subject} — ${c.sender}`).join("");
    }
  } catch(e){ if(res) res.textContent="Error: "+e.message; }
  inp.value="";
}

/* ── Polling ───────────────────────────────────────── */
let _poll=null;
function startEmailPolling(){if(_poll)return;_poll=setInterval(()=>loadFolderBadges(),60000);}
function stopEmailPolling(){if(_poll){clearInterval(_poll);_poll=null;}}

/* ── Toast ─────────────────────────────────────────── */
function toast(msg, type="info") {
  const c=document.getElementById("email-toast-container"); if(!c) return;
  const t=document.createElement("div"); t.className=`email-toast ${type}`; t.textContent=msg;
  c.appendChild(t);
  setTimeout(()=>{t.style.animation="toastOut 0.3s ease forwards";setTimeout(()=>t.remove(),320);},3200);
}

/* ── Helpers ───────────────────────────────────────── */
function esc(s){if(!s)return"";return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
function fmtDate(ts){
  if(!ts)return"";
  const d=new Date(ts*1000),n=new Date(),h=(n-d)/3600000;
  if(h<24&&d.getDate()===n.getDate())return d.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});
  if(h<168)return d.toLocaleDateString([],{weekday:"short"});
  return d.toLocaleDateString([],{month:"short",day:"numeric"});
}
function fmtBytes(b){if(!b)return"0 B";if(b<1024)return b+" B";if(b<1048576)return(b/1024).toFixed(1)+" KB";return(b/1048576).toFixed(1)+" MB";}

/* ── Wire DOM events ───────────────────────────────── */
function wireEmailEvents() {
  // folders
  document.querySelectorAll(".folder-item").forEach(el=>{
    el.addEventListener("click",()=>{
      document.querySelectorAll(".folder-item").forEach(f=>f.classList.remove("active"));
      el.classList.add("active");
      EMAIL.activeFolder=el.dataset.folder; EMAIL.searchQuery="";
      const si=document.getElementById("email-search-input"); if(si) si.value="";
      loadEmailList();
    });
  });
  // search
  document.getElementById("email-search-input")?.addEventListener("input",e=>{
    clearTimeout(EMAIL.searchDebounce);
    EMAIL.searchDebounce=setTimeout(()=>{EMAIL.searchQuery=e.target.value.trim();loadEmailList();},380);
  });
  // account
  document.getElementById("email-account-sel")?.addEventListener("change",e=>{
    EMAIL.activeAccount=e.target.value||null; loadEmailList();
  });
  // toolbar
  document.getElementById("email-sync-btn")?.addEventListener("click",syncEmail);
  document.getElementById("email-compose-btn")?.addEventListener("click",()=>openCompose());
  // compose
  document.getElementById("compose-close-btn")?.addEventListener("click",closeCompose);
  document.getElementById("compose-send-btn")?.addEventListener("click",sendCompose);
  document.getElementById("compose-draft-btn")?.addEventListener("click",aiDraftCompose);
  document.getElementById("compose-cancel-btn")?.addEventListener("click",closeCompose);
  document.getElementById("compose-modal-overlay")?.addEventListener("click",e=>{if(e.target.id==="compose-modal-overlay")closeCompose();});
  // viewer actions
  document.getElementById("email-action-reply")?.addEventListener("click",()=>EMAIL.selectedEmail&&openCompose(EMAIL.selectedEmail));
  document.getElementById("email-action-reply-all")?.addEventListener("click",()=>EMAIL.selectedEmail&&openCompose(EMAIL.selectedEmail));
  document.getElementById("email-action-archive")?.addEventListener("click",()=>EMAIL.selectedEmail&&archiveEmail(EMAIL.selectedEmail.id));
  document.getElementById("email-action-mark-read")?.addEventListener("click",()=>EMAIL.selectedEmail&&markEmailRead(EMAIL.selectedEmail.id,true));
  document.getElementById("email-action-mark-unread")?.addEventListener("click",()=>EMAIL.selectedEmail&&markEmailRead(EMAIL.selectedEmail.id,false));
  document.getElementById("email-action-remind")?.addEventListener("click",()=>EMAIL.selectedEmail&&reminderPrompt(EMAIL.selectedEmail.id));
  document.getElementById("email-action-delete")?.addEventListener("click",()=>{if(EMAIL.selectedEmail&&confirm("Delete?"))archiveEmail(EMAIL.selectedEmail.id);});
  // AI insert
  document.getElementById("ai-insert-reply-btn")?.addEventListener("click",async()=>{
    if(!EMAIL.selectedEmail)return;
    openCompose(EMAIL.selectedEmail); toast("Generating AI reply…","info");
    try{
      const r=await fetch("/api/email/ai/draft",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email_id:EMAIL.selectedEmail.id,intent:"helpful professional reply"})});
      const d=await r.json(); if(d.draft){document.getElementById("compose-body").value=d.draft;toast("Draft inserted!","success");}
    }catch(_){}
  });
  // old inline ask (keep for backward compat)
  document.getElementById("inbox-chat-send-btn")?.addEventListener("click",askInbox);
  document.getElementById("inbox-chat-input")?.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();askInbox();}});
  // sort
  document.getElementById("email-sort-btn")?.addEventListener("click",()=>{
    EMAIL.sortBy=EMAIL.sortBy==="date"?"priority":"date";
    const b=document.getElementById("email-sort-btn");if(b)b.textContent=EMAIL.sortBy==="date"?"↓ Date":"↓ Priority";
    loadEmailList();
  });
  // infinite scroll
  document.getElementById("email-list-scroll")?.addEventListener("scroll",function(){
    if(this.scrollTop+this.clientHeight>=this.scrollHeight-120&&!EMAIL.loading&&EMAIL.emails.length>=60){
      EMAIL.page++; loadEmailList(false);
    }
  });

  // ── Accounts panel ────────────────────────────────
  document.getElementById("email-accounts-btn")?.addEventListener("click", openAccountsPanel);
  document.getElementById("email-accounts-panel-close")?.addEventListener("click", closeAccountsPanel);
  document.getElementById("email-accounts-panel")?.addEventListener("click", e=>{if(e.target.id==="email-accounts-panel")closeAccountsPanel();});
  document.getElementById("accounts-panel-add-btn")?.addEventListener("click", openAddAccount);

  // ── Add Account modal ──────────────────────────────
  document.getElementById("add-account-close-btn")?.addEventListener("click", closeAddAccount);
  document.getElementById("add-account-cancel-btn")?.addEventListener("click", closeAddAccount);
  document.getElementById("add-account-modal-overlay")?.addEventListener("click", e=>{if(e.target.id==="add-account-modal-overlay")closeAddAccount();});
  document.getElementById("add-account-save-btn")?.addEventListener("click", saveAccount);


  document.getElementById("email-ask-btn")?.addEventListener("click", openAskPanel);
  document.getElementById("email-stats-btn")?.addEventListener("click", openStatsPanel);
  document.getElementById("email-scan-spam-btn")?.addEventListener("click", scanSpam);
  document.getElementById("email-scan-reply-btn")?.addEventListener("click", scanNeedsReply);
  document.getElementById("email-watch-btn")?.addEventListener("click", toggleWatch);

  // Ask panel wiring
  document.getElementById("email-ask-panel-close")?.addEventListener("click", closeAskPanel);
  document.getElementById("email-ask-panel")?.addEventListener("click", e=>{if(e.target.id==="email-ask-panel")closeAskPanel();});
  document.getElementById("ask-panel-send-btn")?.addEventListener("click", sendAskPanel);
  document.getElementById("ask-panel-input")?.addEventListener("keydown", e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendAskPanel();}});

  // Stats panel wiring
  document.getElementById("email-stats-panel-close")?.addEventListener("click", closeStatsPanel);
  document.getElementById("email-stats-panel")?.addEventListener("click", e=>{if(e.target.id==="email-stats-panel")closeStatsPanel();});
}

/* ═══════════════════════════════════════════════════
   NEW FEATURES
   ═══════════════════════════════════════════════════ */

/* ── Ask Inbox Panel ─────────────────────────────── */
function openAskPanel() {
  const p = document.getElementById("email-ask-panel");
  if (p) { p.style.display = "flex"; document.getElementById("ask-panel-input")?.focus(); }
}
function closeAskPanel() {
  const p = document.getElementById("email-ask-panel"); if (p) p.style.display = "none";
}
async function sendAskPanel() {
  const inp = document.getElementById("ask-panel-input"); if (!inp) return;
  const q = inp.value.trim(); if (!q) return;
  const res = document.getElementById("ask-panel-result");
  const cit = document.getElementById("ask-panel-citations");
  if (res) { res.textContent = "⏳ Thinking…"; }
  if (cit) { cit.innerHTML = ""; }
  try {
    const r = await fetch("/api/email/ask", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({question: q})
    });
    const d = await r.json();
    if (res) res.textContent = d.answer || d.error || "No answer.";
    if (cit && d.citations?.length) {
      cit.innerHTML = d.citations.map(c =>
        `<span class="citation-chip" title="${esc(c.sender)}">[#${c.id}] ${esc((c.subject||"").slice(0,35))}</span>`
      ).join("");
    }
  } catch(e) {
    if (res) res.textContent = "Error: " + e.message;
  }
  inp.value = "";
}

/* ── Stats Panel ─────────────────────────────────── */
function openStatsPanel() {
  const p = document.getElementById("email-stats-panel"); if (!p) return;
  p.style.display = "flex";
  loadStats();
}
function closeStatsPanel() {
  const p = document.getElementById("email-stats-panel"); if (p) p.style.display = "none";
}
async function loadStats() {
  const body = document.getElementById("email-stats-body"); if (!body) return;
  body.innerHTML = '<div class="email-stats-loading">Loading stats…</div>';
  try {
    const r = await fetch("/api/email/stats");
    const s = await r.json();
    if (s.warning) { body.innerHTML = `<div class="email-stats-loading">⚠ ${esc(s.warning)}</div>`; return; }
    body.innerHTML = `
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-card-value">${s.total ?? 0}</div>
          <div class="stat-card-label">Total Emails</div>
        </div>
        <div class="stat-card">
          <div class="stat-card-value accent-ok">${s.unread ?? 0}</div>
          <div class="stat-card-label">Unread</div>
        </div>
        <div class="stat-card">
          <div class="stat-card-value accent-reply">${s.needs_reply_count ?? 0}</div>
          <div class="stat-card-label">Needs Reply</div>
        </div>
        <div class="stat-card">
          <div class="stat-card-value accent-spam">${s.spam_count ?? 0}</div>
          <div class="stat-card-label">Spam</div>
        </div>
        <div class="stat-card">
          <div class="stat-card-value">${s.newsletter_count ?? 0}</div>
          <div class="stat-card-label">Newsletters</div>
        </div>
        <div class="stat-card">
          <div class="stat-card-value">${s.sent ?? 0}</div>
          <div class="stat-card-label">Sent</div>
        </div>
        <div class="stat-card">
          <div class="stat-card-value">${s.has_attachments ?? 0}</div>
          <div class="stat-card-label">Attachments</div>
        </div>
        <div class="stat-card">
          <div class="stat-card-value accent-reply">${s.suspicious_count ?? 0}</div>
          <div class="stat-card-label">Suspicious</div>
        </div>
      </div>
      ${s.top_contacts?.length ? `
        <div class="stats-section-title">Top Contacts</div>
        ${s.top_contacts.map(([addr, name, count]) => `
          <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border-color);font-size:0.8rem;">
            <span style="color:var(--text-main)">${esc(name||addr)}</span>
            <span style="color:var(--text-muted)">${count} emails</span>
          </div>`).join("")}
      ` : ""}
      <div style="margin-top:12px;font-size:0.72rem;color:var(--text-muted)">
        Storage: ${s.storage_bytes ? fmtBytes(s.storage_bytes) : "—"}
        ${s.last_sync_at ? ` · Last sync: ${fmtDate(s.last_sync_at)}` : ""}
      </div>
    `;
  } catch(e) {
    body.innerHTML = `<div class="email-stats-loading">Error: ${esc(e.message)}</div>`;
  }
}

/* ── Scan Spam ───────────────────────────────────── */
async function scanSpam() {
  const btn = document.getElementById("email-scan-spam-btn"); if (!btn) return;
  btn.textContent = "Scanning…"; btn.disabled = true;
  try {
    const r = await fetch("/api/email/spam/scan", {method:"POST"});
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    toast(`Spam scan done — ${d.flagged ?? 0} flagged`, "success");
    await loadFolderBadges();
    // If already on spam folder, reload
    if (EMAIL.activeFolder === "spam") loadEmailList();
  } catch(e) {
    toast("Spam scan failed: " + e.message, "error");
  } finally {
    btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> Scan Spam`;
    btn.disabled = false;
  }
}

/* ── Scan Needs-Reply ────────────────────────────── */
async function scanNeedsReply() {
  const btn = document.getElementById("email-scan-reply-btn"); if (!btn) return;
  btn.textContent = "Scanning…"; btn.disabled = true;
  try {
    // Reuse newsletters scan endpoint pattern — call p2 scan via spam router
    const r = await fetch("/api/email/p2/scan-reply", {method:"POST"});
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    toast(`Reply scan done — ${d.flagged ?? 0} need reply`, "success");
    await loadFolderBadges();
    if (EMAIL.activeFolder === "needs_reply") loadEmailList();
  } catch(e) {
    // fallback — server may not expose p2 endpoint yet
    toast("Reply scan not available yet. Run 'pm email scan-reply' from terminal.", "info");
  } finally {
    btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg> Scan Needs-Reply`;
    btn.disabled = false;
  }
}

/* ── Watch mode ──────────────────────────────────── */
let _watchInterval = null;
let _watchActive = false;

function toggleWatch() {
  if (_watchActive) stopWatch(); else startWatch();
}
function startWatch() {
  _watchActive = true;
  const lbl = document.getElementById("email-watch-label");
  const status = document.getElementById("email-watch-status");
  const btn = document.getElementById("email-watch-btn");
  if (lbl) lbl.textContent = "Stop Watch";
  if (status) status.style.display = "flex";
  if (btn) btn.classList.add("active");
  _watchInterval = setInterval(async () => {
    const txt = document.getElementById("email-watch-status-text");
    if (txt) txt.textContent = "Checking…";
    try {
      // Quick sync all accounts silently
      const accounts = EMAIL.accounts;
      for (const a of accounts) {
        await fetch("/api/email/sync", {
          method:"POST", headers:{"Content-Type":"application/json"},
          body: JSON.stringify({account_label:a.label, limit:10, run_ai:false})
        });
      }
      await loadFolderBadges();
      if (txt) txt.textContent = `Watching · ${new Date().toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})}`;
    } catch(_) {
      if (txt) txt.textContent = "Watch error";
    }
  }, 60000);
  toast("Watch mode started — checking every 60s", "info");
}
function stopWatch() {
  _watchActive = false;
  if (_watchInterval) { clearInterval(_watchInterval); _watchInterval = null; }
  const lbl = document.getElementById("email-watch-label");
  const status = document.getElementById("email-watch-status");
  const btn = document.getElementById("email-watch-btn");
  if (lbl) lbl.textContent = "Start Watch";
  if (status) status.style.display = "none";
  if (btn) btn.classList.remove("active");
  toast("Watch mode stopped", "info");
}

/* ═══════════════════════════════════════════════════
   ACCOUNTS PANEL
   ═══════════════════════════════════════════════════ */

function openAccountsPanel() {
  const p = document.getElementById("email-accounts-panel");
  if (p) { p.style.display = "flex"; renderAccountsPanel(); }
}
function closeAccountsPanel() {
  const p = document.getElementById("email-accounts-panel"); if (p) p.style.display = "none";
}

async function renderAccountsPanel() {
  const body = document.getElementById("email-accounts-body"); if (!body) return;
  body.innerHTML = '<div class="email-stats-loading">Loading accounts…</div>';
  try {
    const r = await fetch("/api/email/accounts");
    const d = await r.json();
    const accounts = d.accounts || [];
    if (!accounts.length) {
      body.innerHTML = `
        <div style="text-align:center;padding:40px 20px;color:var(--text-muted)">
          <div style="font-size:2rem;margin-bottom:10px">📭</div>
          <div style="font-size:0.9rem;margin-bottom:6px">No email accounts configured yet.</div>
          <div style="font-size:0.78rem">Click <strong style="color:var(--text-main)">+ Add Account</strong> to connect your first inbox.</div>
        </div>`;
      return;
    }
    body.innerHTML = accounts.map(a => {
      const initial = (a.label||a.email||"?").slice(0,2).toUpperCase();
      const [bgC, fgC] = avatarColors(a.label||a.email);
      return `
        <div class="acct-card" data-acct-label="${esc(a.label)}">
          <div class="acct-card-left">
            <div class="email-avatar" style="width:38px;height:38px;background:${bgC};color:${fgC};font-size:0.85rem;border-radius:10px">${initial}</div>
            <div class="acct-card-info">
              <div class="acct-card-label">${esc(a.label)}</div>
              <div class="acct-card-email">${esc(a.email)}</div>
              <div class="acct-card-host">${esc(a.imap_host)} · ${a.use_ssl ? "SSL" : "no-SSL"}</div>
            </div>
          </div>
          <div class="acct-card-actions">
            <button class="compose-btn" onclick="syncAccountFrom('${esc(a.label)}')" id="sync-btn-${esc(a.label)}" style="font-size:0.75rem;padding:4px 10px">
              <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
              Sync
            </button>
            <button class="compose-btn" onclick="deleteAccount('${esc(a.label)}')" style="font-size:0.75rem;padding:4px 10px;color:#f87171;border-color:#3a1a1a" title="Remove account and all its emails">
              <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
              Delete
            </button>
          </div>
        </div>`;
    }).join("") + `
      <div style="padding:14px 0 4px;font-size:0.72rem;color:var(--text-muted);border-top:1px solid var(--border-color);margin-top:8px">
        Credentials are encrypted with Fernet and stored locally in <code style="font-family:monospace">~/.palimind/email.db</code>.
      </div>`;
  } catch(e) {
    body.innerHTML = `<div class="email-stats-loading">⚠ ${esc(e.message)}</div>`;
  }
}

async function syncAccountFrom(label) {
  const btn = document.getElementById(`sync-btn-${label}`); if (!btn) return;
  btn.textContent = "Syncing…"; btn.disabled = true;
  try {
    const r = await fetch("/api/email/sync", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({account_label:label, limit:50, run_ai:true})
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    toast(`Synced ${d.stored ?? 0} new emails from ${label}`, "success");
    await loadFolderBadges(); await loadEmailList();
  } catch(e) {
    toast("Sync failed: " + e.message, "error");
  } finally {
    btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg> Sync`;
    btn.disabled = false;
  }
}

async function deleteAccount(label) {
  const confirmed = confirm(
    `Delete account "${label}" and ALL its emails from the local database?\n\nThis cannot be undone.`
  );
  if (!confirmed) return;

  try {
    const r = await fetch(`/api/email/accounts/${encodeURIComponent(label)}`, {
      method: "DELETE",
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    toast(`Account "${label}" deleted.`, "success");
    // Refresh panel and dropdowns
    await loadEmailAccounts();
    renderAccountsPanel();
    await loadFolderBadges();
    await loadEmailList();
  } catch(e) {
    toast("Delete failed: " + e.message, "error");
  }
}

/* ═══════════════════════════════════════════════════
   ADD ACCOUNT MODAL
   ═══════════════════════════════════════════════════ */

function openAddAccount() {
  closeAccountsPanel();
  const ov = document.getElementById("add-account-modal-overlay");
  if (ov) { ov.classList.add("open"); document.getElementById("acct-label")?.focus(); }
  document.getElementById("add-account-status").textContent = "";
}
function closeAddAccount() {
  document.getElementById("add-account-modal-overlay")?.classList.remove("open");
}

const PROVIDER_PRESETS = {
  gmail:    { imap_host:"imap.gmail.com",         imap_port:993, smtp_host:"smtp.gmail.com",         smtp_port:465 },
  outlook:  { imap_host:"outlook.office365.com",  imap_port:993, smtp_host:"smtp.office365.com",     smtp_port:587 },
  yahoo:    { imap_host:"imap.mail.yahoo.com",    imap_port:993, smtp_host:"smtp.mail.yahoo.com",    smtp_port:465 },
  fastmail: { imap_host:"imap.fastmail.com",      imap_port:993, smtp_host:"smtp.fastmail.com",      smtp_port:465 },
  proton:   { imap_host:"127.0.0.1",              imap_port:1143, smtp_host:"127.0.0.1",             smtp_port:1025 },
};

function acctPreset(provider) {
  const p = PROVIDER_PRESETS[provider]; if (!p) return;
  document.getElementById("acct-imap-host").value = p.imap_host;
  document.getElementById("acct-imap-port").value = p.imap_port;
  document.getElementById("acct-smtp-host").value = p.smtp_host;
  document.getElementById("acct-smtp-port").value = p.smtp_port;
  // Auto-fill label if blank
  const lbl = document.getElementById("acct-label"); if (lbl && !lbl.value) lbl.value = provider;
  document.getElementById("acct-label")?.focus();
}

async function saveAccount() {
  const label    = document.getElementById("acct-label").value.trim();
  const email    = document.getElementById("acct-email").value.trim();
  const password = document.getElementById("acct-password").value;
  const imapHost = document.getElementById("acct-imap-host").value.trim();
  const imapPort = parseInt(document.getElementById("acct-imap-port").value) || 993;
  const smtpHost = document.getElementById("acct-smtp-host").value.trim();
  const smtpPort = parseInt(document.getElementById("acct-smtp-port").value) || 465;
  const username = document.getElementById("acct-username").value.trim();
  const useSsl   = document.getElementById("acct-ssl").checked;
  const testConn = document.getElementById("acct-test").checked;

  const status = document.getElementById("add-account-status");

  if (!label)    { status.textContent = "⚠ Label is required."; return; }
  if (!email)    { status.textContent = "⚠ Email address is required."; return; }
  if (!password) { status.textContent = "⚠ Password is required."; return; }
  if (!imapHost) { status.textContent = "⚠ IMAP host is required."; return; }
  if (!smtpHost) { status.textContent = "⚠ SMTP host is required."; return; }

  const btn = document.getElementById("add-account-save-btn");
  btn.textContent = "Saving…"; btn.disabled = true;
  status.textContent = testConn ? "Testing connection…" : "";

  try {
    const r = await fetch("/api/email/accounts", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        label, email_address:email, password,
        imap_host:imapHost, imap_port:imapPort,
        smtp_host:smtpHost, smtp_port:smtpPort,
        username: username || null,
        use_ssl: useSsl,
        test_connection: testConn,
      }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    toast(`Account "${label}" added successfully!`, "success");
    closeAddAccount();
    // Clear form
    ["acct-label","acct-email","acct-password","acct-imap-host","acct-smtp-host","acct-username"].forEach(id=>{
      const el = document.getElementById(id); if(el) el.value = "";
    });
    document.getElementById("acct-imap-port").value = "993";
    document.getElementById("acct-smtp-port").value = "465";
    // Reload accounts everywhere
    await loadEmailAccounts();
    // Offer sync
    toast(`Run Sync or open Accounts to sync "${label}"`, "info");
  } catch(e) {
    status.textContent = "⚠ " + e.message;
    status.style.color = "#f87171";
  } finally {
    btn.textContent = "Add Account"; btn.disabled = false;
    status.style.color = "";
  }
}
