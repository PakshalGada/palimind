# OpenBot → PaliMind Agents implementation plan

Status: **plan only** — no production code, model call, model test, or model benchmark was run.

This plan turns the feature review in
[`openbot-feature-inventory.md`](openbot-feature-inventory.md) into concrete work
for PaliMind's agent runtime. It is written for the Python backend in
`packages/backend/palimind/` and the React frontend in `packages/frontend/`.
It preserves PaliMind's local-first, approval-gated, sandboxed design.

## 1. Executive summary

OpenBot is broader than PaliMind in four areas that matter to agents:

1. **Provider harnesses.** OpenBot runs Codex, Claude, Grok, OpenCode, Gemini,
   Cursor, Cline, Pi, Muse, custom ACP agents, custom OpenAI-compatible
   endpoints, and local model servers behind one provider boundary. PaliMind
   currently runs Ollama plus an OpenCode-compatible proxy.
2. **Work management.** OpenBot has per-agent tasks, a durable mailbox, queue
   holds, agent-to-agent messages, shared channels, and prompt-driven agent
   management. PaliMind has a durable queue, teams, and a run history, but not
   separate task lanes or a general mailbox.
3. **Automation surface.** OpenBot has routine sessions, routine flows, event
   waits, a local scripts API/CLI, signed webhook routines, and a calendar feed.
   PaliMind has routines, workflows, webhook tokens, and jobs, but not the agent
   facing automation contract.
4. **Agent environment.** OpenBot has a persistent embedded browser with
   profiles and takeover, cross-platform Computer Use, a skill/plugin ecosystem,
   visual replies, and import/export/transfer. PaliMind has headless Playwright,
   Linux-only Computer Use, JSON/YAML skills, and MCP tools.

PaliMind also has things OpenBot does not: a RAG workspace, local knowledge
graph, document/office/data tools, local image generation, deep research, MoE,
memory 2.0, a local OpenAI-compatible API, and a small dependency-free web
client. The plan keeps those and fills the agent-runtime gaps.

**Recommended delivery order:** foundation → tasks/mailbox → provider harnesses
→ channels → routines/flows/waits/automation → browser/Computer Use → skills/
plugins → sharing/visual replies → usage/observability → remote/mobile.

**Deliberately deferred:** OpenBot's Cloudflare account service, Stripe billing,
hosted sites, public status page, marketing analytics, Electron release
machinery, and remote desktop. These are product-boundary features, not agent
runtime features, and several conflict with PaliMind's local-first/no-telemetry
position.

---

## 2. PaliMind baseline

The plan reuses these existing modules instead of replacing them.

| Area | PaliMind today | Evidence |
|---|---|---|
| Agent definitions | `AgentDefinition` with identity, prompt, model, temperature, context budget, tools, tier policy, autonomy, memory, knowledge scope, concurrency, approval, skills, planning, orchestration, desktop access. | `packages/backend/palimind/agents/catalog.py` |
| Agent runtime | Agent loop, tool calls, approvals, steer/pause/resume/cancel, adaptive reasoning, planner, self-critique, escalation, model routing, suggestions, todo checklist, citations, usage. | `packages/backend/palimind/agents/runtime.py` |
| Durable runs | Run journal, bounded checkpoints, resume after restart, run history. | `agents/run_journal.py`, `agents/run_state.py` |
| Queue | Per-target FIFO queue with priority, pause/resume/cancel, stale-run recovery, durable job bridge. | `agents/queue.py` |
| Jobs | SQLite jobs with leases, retries, backoff, cron/interval recurrence, dead-letter, workers. | `palimind/jobs/service.py`, `jobs/handlers.py` |
| Teams | Manager, roundtable, and chain modes; team chat, blackboard, notes, approvals, runs. | `agents/teams.py`, `agents/team_runtime.py`, `agents/teams_api.py` |
| Routines | Manual/scheduled/watcher/webhook triggers, run history, result notifications. | `agents/routines.py`, `agents/scheduler.py` |
| Workflows | JSON DAG of agent and tool nodes, manual/cron/file/webhook triggers, durable runs. | `palimind/workflows/` |
| Goals / background tasks | Goal progress, `/loop` scheduling, notifications, 50-task / 7-day limits. | `agents/goals.py` |
| Memory | Hybrid vector + lexical recall, confidence/recency, edit/forget, `remember`/`forget`. | `agents/memory.py`, `agents/memory_api.py` |
| Skills | JSON/YAML skills, validation, install/uninstall/export, marketplace, slash commands. | `agents/skills.py` |
| MCP | Trusted stdio servers, tool registration, reload. | `agents/mcp.py`, `api_routers/routers/mcp.py` |
| Tools | Typed schemas, tiers, approval, parallel read-only calls, router, audit, drop-in user tools. | `agents/tools/`, `agents/tool_router.py`, `llm/mixture_of_expert/tools.py` |
| Browser | Headless Playwright session, SSRF/domain policy, navigate/inspect/click/type/screenshot/tabs. | `agents/tools/browser/tool.py` |
| Desktop | Linux AT-SPI accessibility refs, screenshots, physical fallback, policy, audit, rate limit. | `agents/tools/desktop/`, `packages/desktop-native/` |
| HTTP API | FastAPI app, agent/team APIs, SSE with replay, OpenAI-compatible `/v1`, web client, metrics, backup. | `api_server.py`, `agents/api.py`, `agents/teams_api.py`, `events/` |
| UI | Agents workspace: home live run, chat, teams, runs, kanban, approvals inbox, workspace files, wizard/settings. | `packages/frontend/src/features/agents/` |
| Security | Per-install bearer token, loopback default, approval gate, tool audit, sandboxed shell/Python, backup encryption. | `security/`, `agents/tools/sandbox.py`, `README.md` (Security) |

### 2.1 Baseline gaps, stated plainly

- Agents cannot run as separate task lanes; the queue targets an agent or a
  team, not a task thread.
- Messages do not form a general mailbox with replies, reactions, file
  transfers, deliveries, holds, and idempotency.
- Providers are Ollama/OpenCode-proxy only. There is no ACP client, no Codex or
  Claude harness, no provider account model, and no backup-model failover.
- Teams are not shared channels: there is no deterministic owner selection,
  channel task revision, human/agent membership model, archive/restore, or
  channel memory/context packet.
- Routines are basic; there are no routine sessions, quiet/failed-run tools,
  routine flows, event waits, local automation API/CLI, signed webhook
  receipts/filters, or calendar feed.
- The browser is a single headless session, not a persistent user-visible
  browser with profiles, tab lifecycle, downloads, and takeover.
- Computer Use is Linux-only and has no cross-platform driver abstraction.
- Skills are simple records; there is no Agent Skills folder layout, immutable
  local revision library, plugin catalog, share links, or connector/sign-in
  system.
- There is no visual reply (`html_render`/`html_preview`), agent import/export/
  transfer, or agent template link.
- There is no remote host/Team API or native mobile client.

---

## 3. Gap matrix and decisions

Priority: **P0** = unblocks several later features; **P1** = high user value,
local-only; **P2** = important but larger or platform-specific; **P3** = defer.

| OpenBot IDs | Capability | PaliMind today | Decision | Priority / phase |
|---|---|---|---|---|
| OB-20…OB-29 | Persistent profiles, sections, hidden agents, prompt-driven profile tools, import/transfer/templates | Profiles exist; no section/hidden state; profile tools are partial; no import/transfer/template | **Adopt/adapt** | P1 (Phase 1, 7) |
| OB-30…OB-32 | Subagents, shared agent data tables, per-agent memories | Orchestrator fan-out and memory 2.0 exist; no in-turn child registry or shared data namespace | **Adopt/adapt** | P1/P2 (Phase 1, 6) |
| OB-40…OB-56 | Provider harnesses, runtime management, accounts, model catalog, failover, Inception-style local provider | Ollama + OpenCode proxy only | **Adopt** via provider abstraction; ACP/Codex/Claude first | P0/P1 (Phase 2) |
| OB-60…OB-67 | Queue, mailbox, tasks, holds, recovery | Queue and jobs exist; no task lanes/mailbox | **Adopt** | P0 (Phase 1) |
| OB-80…OB-85 | Agent messages, delegation policy, interruption, reactions, side questions | `ask_agent`, team notes, approvals; no mailbox/reactions/interrupt tool; no side questions | **Adopt/adapt** | P1 (Phase 1/3) |
| OB-90…OB-97 | Shared channels | Teams only | **Adopt** as a new channel layer; keep teams | P1 (Phase 3) |
| OB-110…OB-121 | Routines, flows, waits, local scripts, webhooks, calendar | Routines/workflows/jobs exist; no flows/waits/automation contract | **Adopt** | P1 (Phase 4) |
| OB-140…OB-147 | Embedded browser, profiles, takeover, downloads, remote live view | Headless Playwright only; no remote live view | **Adopt/adapt**; remote view in Phase 9 | P2 (Phase 5) |
| OB-160…OB-163 | Cross-platform Computer Use, remote desktop | Linux AT-SPI only | **Adopt** driver abstraction; defer remote desktop | P2 (Phase 5) |
| OB-180…OB-187 | Skills folders/library, plugins, MCP management, connectors | JSON/YAML skills + MCP reload | **Adopt/adapt**; defer 1Password/Bitwarden | P2 (Phase 6) |
| OB-200…OB-204 | Visual replies, UI blocks, attachments | Artifacts and uploads exist; no `html_render`; attachment contract simpler | **Adopt** visual replies; extend attachments | P2 (Phase 7) |
| OB-220…OB-226 | Team API, remote host, mobile, web client, per-agent roles | No remote host/mobile; `/client` is a basic chat page; no per-agent roles | **Defer/adapt** | P3 (Phase 9) |
| OB-05/06/07/08 | Accounts, billing, hosted sites, status page | Not present; not local-first | **Reject/defer** | — |
| OB-13 | Multi-tenant macOS hosting | Not present; PaliMind is a single-user desktop app | **Reject/defer** | — |
| OB-09 | Agent usage analytics + resource sampling | Metrics and run usage exist; no per-agent usage report | **Adopt** local usage; reject external analytics | P2 (Phase 8) |
| OB-10 | Multi-language i18n | English UI | **Defer** | P3 |
| OB-240…OB-246 | Security principles | Approval gate, sandbox, token, audit already exist | **Adapt principles**, not code | Continuous |

---

## 4. Target architecture

```
packages/backend/palimind/
  agents/
    providers/                 # new: provider boundary
      base.py                  # ProviderClient protocol, capabilities, events
      registry.py              # provider discovery, model catalog merge
      ollama.py                # wraps existing Ollama client
      opencode.py              # wraps existing opencode router/proxy
      openai_compat.py         # custom endpoints
      acp.py                   # JSON-RPC over stdio, generic ACP
      codex.py                 # Codex app-server adapter
      claude.py                # Claude stream-json adapter
      runtime_manager.py       # detection, pinned runtime store, updates
    tasks.py                   # task lanes and task records
    mailbox.py                 # deliveries, replies, reactions, transfers
    channels.py                # shared group chats, routing, channel tasks
    flows.py                   # routine flows
    waits.py                   # await_event/list_waits/close_wait
    automation.py              # loopback local-scripts server
    usage.py                   # local usage aggregation
    sharing.py                 # import/export/transfer/templates
    sections.py                # agent sidebar sections
    browser/
      host.py                  # persistent browser host, profiles, tabs
      takeover.py              # secure input/takeover bridge
    tools/
      ...                      # existing tools; add task/mailbox/channel tools
  storage/
    state_store.py             # schema additions/migrations
  api_routers/routers/
    providers.py               # new
    tasks.py                   # new (or extend agents/api.py)
    channels.py                # new
    automation.py              # new (loopback-only)
    browser.py                 # extend desktop/browser routes
    usage.py                   # new
  settings.py                  # feature flags and limits
```

**Boundary rules**

- A provider adapter owns one process/protocol and emits normalized events
  (`turn_started`, `message_delta`, `tool_call`, `tool_result`, `usage`,
  `question`, `approval`, `error`, `turn_completed`). It does not write UI
  state.
- The agent runtime owns policy: approvals, tool routing, sandbox, task
  limits, holds, redaction, and persistence.
- A tool is a thin adapter over a service. `start_task`, `send_message`,
  `await_event`, and channel tools delegate to `tasks.py`, `mailbox.py`,
  `waits.py`, and `channels.py`.
- Routers only decode/validate and dispatch. No business logic in
  `api_routers/`.
- New state goes into `state_store.py` or the workspace SQLite store, not into
  ad-hoc JSON files. Every schema change needs an idempotent migration and a
  regression test that opens an old database.
- Every user-visible string follows the existing pattern (no new i18n system is
  required for the first phases; keep English strings centralized where the
  current UI already does).

---

## 5. Data model additions

Create tables in `storage/state_store.py` (global, per-user state DB) unless a
table is workspace-scoped.

### 5.1 Threads and agent profiles

| Table | Key fields | Purpose |
|---|---|---|
| `agent_threads` | `id`, `agent_id`, `kind` (`chat`/`task`/`channel`/`routine`/`messaging`), `provider`, `provider_session_id`, `status`, `metadata`, `created_at`, `updated_at`, `archived_at` | One durable thread per conversation; replaces implicit provider-session binding. |
| `agent_sections` | `id`, `name`, `sort_order`, `created_at` | Sidebar sections. |
| `agent_section_assignments` | `agent_id`, `section_id` | One section per agent. |
| `provider_sessions` | `thread_id`, `provider`, `session_id`, `fingerprint`, `state`, `updated_at` | Provider resume state and handoff. |
| `provider_accounts` | `id`, `provider`, `label`, `state`, `metadata` | Account list; secrets live in the OS secret store/token file, never here. |
| `usage_records` | `id`, `agent_id`, `thread_id`, `provider`, `model`, `prompt_tokens`, `completion_tokens`, `cost_estimate`, `day`, `created_at` | Local usage analytics. |

### 5.2 Tasks, mailbox, channels

| Table | Key fields | Purpose |
|---|---|---|
| `agent_tasks` | `id`, `agent_id`, `thread_id`, `title`, `status`, `parent_task_id`, `owner_agent_id`, `revision`, `priority`, `created_at`, `closed_at`, `error` | Separate task lane. |
| `mailbox_deliveries` | `id`, `sender_kind`, `sender_id`, `target_agent_id`, `target_thread_id`, `task_id`, `text`, `attachments`, `status`, `hold_reason`, `attempts`, `idempotency_key`, `created_at`, `started_at`, `finished_at`, `answer`, `error` | Durable message/delivery. |
| `delivery_events` | `delivery_id`, `seq`, `event`, `payload`, `created_at` | Audit/replay of a delivery. |
| `agent_reactions` | `message_id`, `actor_kind`, `actor_id`, `emoji`, `created_at` | Reactions. |
| `agent_waits` | `id`, `agent_id`, `note`, `routine_id`, `status`, `created_at`, `closed_at` | `await_event` records. |
| `channels` | `id`, `name`, `purpose`, `lead_agent_id`, `status`, `created_at`, `archived_at` | Shared channel. |
| `channel_members` | `channel_id`, `agent_id`, `role`, `instructions` | Agent membership. |
| `channel_messages` | `channel_id`, `seq`, `author_kind`, `author_id`, `text`, `task_id`, `attachments`, `created_at` | Canonical channel transcript. |
| `channel_tasks` | `id`, `channel_id`, `owner_agent_id`, `parent_id`, `revision`, `status`, `request`, `result`, `created_at`, `finished_at` | Channel task ownership. |
| `channel_receipts` | `channel_id`, `operation_id`, `actor_id`, `created_at` | Idempotent channel commands. |
| `channel_memories` | `channel_id`, `key`, `value`, `updated_at` | Shared channel facts. |
| `routine_flows` | `id`, `canvas_agent_id`, `routine_id`, `links`, `positions`, `updated_at` | Routine flow canvas. |
| `routine_flow_steps` | `id`, `flow_id`, `from_routine`, `to_agent`, `from_run`, `status`, `input`, `output`, `error`, `updated_at` | Handoff steps. |
| `webhook_receipts` | `route_id`, `delivery_id`, `routine_id`, `status`, `created_at` | Duplicate suppression. |
| `browser_profiles` | `id`, `name`, `color`, `partition`, `created_at` | Named browser profiles. |
| `browser_tabs` | `id`, `profile_id`, `agent_id`, `url`, `title`, `opener_tab_id`, `state`, `updated_at` | Durable tab state. |

### 5.3 Extension to `AgentDefinition`

Add fields with safe defaults so existing agent JSON keeps loading:

```python
provider: str = "ollama"          # ollama | opencode | anthropic | openai | acp:...
provider_account_id: str = ""
backup_models: list[dict] = []    # [{provider, model, account}]
browser_profile: str = "shared"
section_id: str = ""
hidden_at: str = ""
task_limit: int = 2
busy_message_mode: str = "queue"  # queue | steer
allow_automation: bool = False
notifications: dict = {}
```

Update `SCHEMA_VERSION` and `AgentDefinition.from_dict` with an explicit
migration path. Existing `model` values keep working by treating an unknown
prefix as `ollama`/legacy routing.

---

## 6. Phased implementation plan

### Phase 0 — Foundations (P0, ~2 engineer-weeks)

**Outcome:** a provider boundary, thread identity, event envelope, and migration
discipline exist before feature work.

**Work**

1. Add `agents/providers/base.py`:
   - `ProviderCapabilities` (tools, vision, reasoning, context, concurrent
     turns, steering, usage, accounts, attachments).
   - `ProviderEvent` dataclasses and a normalized event union.
   - `ProviderClient` protocol: `list_models`, `start_session`, `resume_session`,
     `send_turn`, `interrupt`, `read_usage`, `close`.
2. Add `agents/providers/registry.py` and adapt the existing Ollama and
   OpenCode paths behind it. The old `llm_chat` call sites stay as the Ollama
   implementation detail.
3. Add `agent_threads`, `provider_sessions`, and `usage_records` tables plus an
   idempotent migration. Backfill one chat thread per existing agent on first
   open.
4. Define normalized event names and payloads in `agents/events.py` (or extend
   the existing `events` package) for: `provider:status`, `provider:models`,
   `provider:usage`, `task:*`, `mailbox:*`, `channel:*`, `wait:*`, `flow:*`,
   `browser:*`, `usage:*`.
5. Add feature flags in `settings.py`:
   `PALIMIND_AGENT_TASKS`, `PALIMIND_AGENT_MAILBOX`,
   `PALIMIND_AGENT_CHANNELS`, `PALIMIND_AGENT_FLOWS`,
   `PALIMIND_AGENT_WAITS`, `PALIMIND_AGENT_AUTOMATION`,
   `PALIMIND_AGENT_BROWSER_PROFILES`, `PALIMIND_AGENT_USAGE`.
   Default off for experimental phases, on for stable phases.
6. Add `tests/fakes/provider.py`: a deterministic scripted provider that emits
   events, tool calls, usage, questions, and failures without a model.

**Acceptance (deterministic only)**

- `pytest packages/backend/tests/test_provider_contract.py` passes with the fake
  provider.
- Migration test opens a pre-change state DB, starts PaliMind, and verifies
  agents, runs, queue, teams, and routines are unchanged.
- No test starts Ollama, OpenCode, or any model process.

---

### Phase 1 — Tasks, mailbox, and agent management (P0/P1, ~5 engineer-weeks)

**Outcome:** an agent can run several explicit tasks, receive durable messages
from users/scripts/other agents, and manage its own profile the way OpenBot
agents do.

#### 1.1 Task lanes

- `agents/tasks.py`: create/read/list/update/close/reopen tasks; enforce
  `task_limit` (default 2, maximum 8), 50 open tasks per agent, and one provider
  turn per lane.
- Extend `agents/queue.py`: queue items carry `lane` (`chat`, `task:<id>`,
  `channel:<id>`), `task_id`, `hold_reason`, and `idempotency_key`. Keep the
  existing `agent`/`team` target types working.
- Extend `agents/runtime.py` busy accounting to per-lane, not per-agent only.
  A task turn must not block the main chat unless the provider is
  `concurrent_turns=false`.
- `agents/run_state.py`: checkpoint includes `thread_id`/`task_id`; resume
  returns to the same lane.
- Crash recovery: on startup, mark `running` task turns `interrupted` and
  requeue only when the previous process did not confirm completion.

#### 1.2 Mailbox

- `agents/mailbox.py`: `send`, `reply`, `react`, `attach`, `deliver`,
  `mark_terminal`, `list`, `get`, `cancel`, `retry`.
- Delivery states: `queued`, `starting`, `running`, `completed`, `failed`,
  `interrupted`, `cancelled`; holds: `task-limit`, `agent-busy`,
  `usage-limit`, `restarting`, `hidden`, `one-turn`.
- Idempotency: `(target_agent_id, idempotency_key)` returns the first receipt
  for 24 hours, including after restart.
- Attachments: store content-addressed bytes under `~/.palimind/uploads` (the
  existing upload store), hash them, and expose only a safe file id/path to the
  model. Never let the model name an arbitrary host path.
- Agent-to-agent messages go through the same mailbox; `ask_agent` becomes a
  convenience wrapper that waits for a delivery when the caller is interactive.

#### 1.3 Tools

Add typed tools in `agents/tools/` and register them in
`llm/mixture_of_expert/tools.py`/the tool registry:

| Tool | Behaviour | Tier/approval |
|---|---|---|
| `start_task` | Create a task lane and enqueue its first message; returns task id. | tier 1, no approval |
| `send_message` | Send text/files to an agent, task, or channel; optional `expects_reply`. | tier 2, approval if it targets another agent |
| `interrupt_agent` | Interrupt only the caller's request on another agent; refuse self/channel/user work. | tier 2, approval |
| `react_to_user_message` | Add a reaction to a user message. | tier 1 |
| `attach_files_to_response` | Attach a workspace file to the current answer. | tier 2, approval |
| `list_agents` / `read_agent` | See agent status, queue, task counts, profile, skills, routines, MCP names (no secrets). | tier 1 |
| `create_agent` / `update_profile` / `update_agents` | Create/edit agents with validated provider/model/effort/tools/access; only the user may widen access. | tier 2, approval |
| `list_models` | List models per provider and account; no credentials. | tier 1 |
| `start_new_chat` | Write a context-reset marker and end provider sessions for that thread. | tier 2 |
| `list_sections` / `create_section` / `rename_section` / `delete_section` / `assign_agent_section` | Sidebar organization. | tier 1/2 |

#### 1.4 HTTP API

Add to `agents/api.py` (or a new `tasks_api.py` included by `api_server.py`):

- `GET/POST /api/agents/{id}/tasks`
- `GET/PATCH/DELETE /api/agents/{id}/tasks/{task_id}`
- `POST /api/agents/{id}/tasks/{task_id}/send`
- `POST /api/agents/{id}/tasks/{task_id}/stop`
- `POST /api/agents/{id}/tasks/{task_id}/close`
- `POST /api/agents/{id}/tasks/{task_id}/reopen`
- `POST /api/agents/{id}/messages`
- `GET /api/agents/{id}/deliveries/{delivery_id}`
- `POST /api/agents/{id}/interrupt`
- `POST /api/agents/{id}/context/clear`
- `GET /api/agents/{id}/pending`
- `POST /api/agents/{id}/prompts/{request_id}/answer`
- `POST /api/agents/{id}/approvals/{request_id}/respond`
- `GET/POST /api/agents/{id}/waits` and `DELETE /api/agents/{id}/waits/{wait_id}`
- `GET/PATCH /api/agents/{id}/sections` and assignment routes
- `GET /api/agents/{id}/usage`
- `POST /api/agents/{id}/side-questions` (ephemeral, no transcript write)

All routes keep the existing bearer token/loopback policy and redact secrets
from responses. SSE events flow through the existing `/api/events` hub with
`Last-Event-ID` replay.

#### 1.5 Subagents and side questions

- Add a per-turn subagent registry (`agent_subagents` or a bounded field on the
  run state) for child agents that the provider starts inside one turn. Store
  title, agent id, status, and result; emit `agent:subagent`; include the list
  in the conversation payload so the UI can render a subagent row. Reuse the
  existing orchestrator/fan-out budget instead of adding a second scheduler.
- Add `POST /api/agents/{id}/side-questions` with `{question, earlier[]}`:
  answer from the agent's profile and the end of its chat with no tools, no
  transcript write, and no more than 20 earlier question/answer pairs. Refuse
  while the provider is busy or at a usage limit. This mirrors OB-85.

#### 1.6 UI

- Add a **Tasks** tab to `packages/frontend/src/features/agents/AgentsWorkspace.tsx`.
- Add `TaskList`, `TaskConversation`, and task actions (Send, Stop, Close,
  Reopen, Run as task) under `features/agents/`.
- Add delivery status rows under the agent activity and a **Pending** panel
  reusing `AgentsInbox`.
- Add hidden-agent and section controls to `AgentListPanel`/`AgentManager`.
- Add a task badge and live task card to `AgentsHome`.
- Add a subagent row under the parent message and a side-question popover.

**Acceptance**

- A task turn and the main chat run concurrently when the fake provider reports
  `concurrent_turns=true`; with `false`, they serialize.
- A duplicate `clientMessageId` returns the same delivery and does not run twice.
- A crash between `starting` and `running` leaves the delivery resumable, not
  lost.
- `interrupt_agent` refuses the caller itself and a channel turn.
- Task limits, open-task limits, and queue holds are enforced and tested.
- A side question never appears in the agent transcript.
- Subagent status/results survive a reload and do not create a second turn.
- UI typecheck and reducer tests pass; no model required.

---

### Phase 2 — Provider harnesses (P0/P1, ~8–10 engineer-weeks)

**Outcome:** PaliMind agents can run on external harnesses and local model
servers through one provider boundary, with honest capability reporting and
failover.

#### 2.1 Generic ACP client

- `agents/providers/acp.py`: JSON-RPC over stdio with content-length framing,
  request/response correlation, streamed message deltas, tool calls,
  permissions, cancellation, session start/resume, and process cleanup.
- Map ACP permission requests to PaliMind's approval gate. Map ACP tools to the
  existing tool registry where possible; otherwise expose them as provider
  tools with the same audit/redaction rules.
- Fixture server under `tests/fixtures/acp_server.py` for deterministic protocol
  tests.

#### 2.2 Concrete adapters

- `codex.py`: Codex App Server over stdio JSONL; thread start/resume, developer
  instructions, dynamic tool declarations, history read, usage.
- `claude.py`: Claude Agent SDK/stream-json; session start/resume, SDK MCP
  bridge, question flow.
- `opencode.py`: wrap the existing OpenCode proxy/router, preserving PaliMind's
  current key detection and model list.
- `ollama.py`: wrap the existing `llm/mixture_of_expert/llm.py` functions.
- `openai_compat.py`: custom base URL, key, headers, model list, streaming and
  native `tool_calls`.
- `grok.py`, `gemini.py`, `cursor.py`, `cline.py`, `pi.py`, `muse.py`: initially
  thin ACP presets (command + env + auth flow), added when the generic ACP
  client is stable.
- `inception.py`: local-only Inception/Mercury preset on Pi's managed CLI when
  its license and key flow are acceptable (OB-56).
- `custom_acp.py`: user-defined command, args, env, working directory; validate
  before saving and never let a model set arbitrary headers/secrets.

#### 2.3 Provider runtime manager

- `agents/providers/runtime_manager.py` and `provider-runtime.lock.json`:
  per-platform artifact URLs, SHA-256 digests, version, license, and install
  layout.
- Resolution precedence: explicit `PALIMIND_*_PATH` → managed copy → system
  `PATH` → not installed. Never auto-update without a user action.
- Download to a staging directory, verify digest, atomically rename, and keep
  the previous version until the new one passes an initialization check.
- Refuse to replace a runtime while a turn is active; queue the update.
- Never run a provider's own updater.

#### 2.4 Provider accounts, model catalog, failover

- `provider_accounts` and `provider_account` selection per agent; secrets in a
  `0600` token file or OS secret store, never in SQLite or prompts.
- Merge model catalogs from Ollama, OpenCode, ACP `session/new`, and custom
  endpoints. Include capabilities (tools, vision, reasoning, context), default
  model, and free/paid label where known.
- Add `backup_models` (max 8) and a deterministic failover gate:
  - classify provider failure (`billing`, `unavailable`, `rate_limit`,
    `auth`, `network`, `timeout`);
  - move only when the turn did no work;
  - keep a 10-minute hold per failed model;
  - return to the primary when its hold ends;
  - never fail over a task/channel turn or a provider that failed to start.
- Emit `provider:model-changed` and `provider:usage`; store usage records.

#### 2.5 UI

- Add **Settings → Providers** with status, version, source (managed/system),
  install/update, sign-in, accounts, model list, and default model.
- Add provider/model/effort/account/backup-model controls to agent settings.
- Show route/failover reasons in run history.

**Acceptance**

- ACP protocol fixture tests cover initialize, session/new, streamed deltas,
  tool call, permission, cancel, error, and close.
- Codex/Claude/OpenCode fixture tests run against captured protocol transcripts
  (no live CLI, no model).
- Runtime manager tests cover digest mismatch, canceled download, active-turn
  deferral, and previous-version rollback.
- Failover tests use a fake provider that returns each failure class.
- No live model inference and no benchmark suite is run.

---

### Phase 3 — Shared channels (P1, ~6–8 engineer-weeks)

**Outcome:** a durable group chat where a human and several agents share one
transcript, with deterministic ownership, delegation, and lifecycle controls.

#### 3.1 Store and service

- `agents/channels.py` over `channels`, `channel_members`, `channel_messages`,
  `channel_tasks`, `channel_receipts`, `channel_memories`.
- Per-channel sequence and stable message ids; command receipts make retries
  idempotent.
- Archive/restore keeps records; delete is explicit.
- Each channel-agent pair gets its own thread (`agent_threads.kind='channel'`),
  never replacing the agent's chat thread.

#### 3.2 Routing and tasks

- Deterministic owner selection in this order: explicit recipient → task
  attached to a reply → reply to a member message with no task → clear
  follow-up to the sole open task → channel with one available member.
- Only when deterministic selection fails, use the lead agent in a separate
  session with no work tools; the lead returns a structured decision (task,
  question, or no work).
- Channel tasks reuse `agent_tasks`/`mailbox_deliveries`; add parent/child
  links, revision checks, ownership transfer, and the 8-child / 2-active
  limits.
- Stop pauses a task and its descendants; Resume continues; Reassign waits for
  the old owner to stop; Archive stops work but keeps history; Restore resumes
  intake.

#### 3.3 Tools and API

Tools: `channel_history`, `channel_assign_task`, `channel_transfer_task`,
`channel_report_result`, `channel_add_member`, `channel_remove_member`,
`channel_set_instructions`, `channel_list_routines`, `channel_create_routine`,
`channel_update_routine`, `channel_delete_routine`.

API: `/api/channels` CRUD, `/api/channels/{id}/messages`,
`/api/channels/{id}/tasks`, `/api/channels/{id}/stop|resume|archive|restore`,
`/api/channels/{id}/memories`, `/api/channels/{id}/routines`.

#### 3.4 UI

- Add a **Channels** view (or a Channels section in Teams) with member avatars,
  author labels, task ownership, and a settings panel.
- Reuse the chat composer; channel messages can carry plan cards, questions,
  and approvals.
- Show channel approvals/browser steps in the channel, not only the agent chat.

**Acceptance**

- Deterministic routing table tests cover every selection rule.
- Duplicate channel commands with the same operation id apply once.
- A stale task revision cannot complete a corrected request.
- Archive stops work; restore starts no backlog.
- Channel turn does not consume the agent's task slots.

---

### Phase 4 — Routines, flows, waits, and local automation (P1, ~7–9 engineer-weeks)

**Outcome:** agents can schedule real work, hand results to other agents, wait
for external events without polling, and be driven by local scripts.

#### 4.1 Routine semantics

Extend `agents/routines.py` and `agents/scheduler.py`:

- `run_source` (`test`, `script`, `webhook`, `schedule`) and `quiet` support.
- `routine_no_update` tool + `[[no-update]]` marker.
- `routine_report_failure` tool; a failed run keeps its answer but records a
  redacted `error`.
- Routine sessions: start an ephemeral thread with `persistSession=false`, a
  short chat handoff (≤8k chars), then append a ≤1.5k digest (≤6k total) to the
  chat handoff.
- Missed-run policies: `run`, `skip`, `catch_up` with a bounded backlog.
- Calendar feed: loopback tokenized `GET /api/routines/calendar.ics?token=...`
  (token `<userData>` file, 0600), next 30 days, no cloud access.

#### 4.2 Routine flows

- `agents/flows.py` store/runtime for the flow tables.
- A link belongs to one routine and applies to runs started after it is
  created.
- Fan-in waits for all inputs; an agent whose inputs all failed is skipped.
- Handoffs are mailbox deliveries that name the same routine/run; a failure in
  a handoff fails only that step.
- Sweep on turn/queue/routine events; one sweep at a time; startup sweep
  recovers interrupted flows.
- Tools: `list_routine_flows`, `connect_routine_agents`,
  `disconnect_routine_agents`.

#### 4.3 Waits and automation API

- `agents/waits.py`: at most 20 open waits per agent; a routine or script run
  wakes matching waits; wake payload repeats the request and note.
- `agents/automation.py`: a separate loopback listener, only while an agent has
  `allow_automation=true`.
  - Files under `~/.palimind/automation/` (`url`, `token`, `headers`) with
    `0700` directory and `0600` files; new token/port at each start; delete when
    off.
  - Refuse `Origin` and foreign `Host` before token check.
  - Routes: `GET /v1/agents`, `POST /v1/agents/{id}/routines/{rid}/run`,
    `POST /v1/agents/{id}/messages`,
    `GET /v1/agents/{id}/deliveries/{did}`,
    `POST /v1/agents/{id}/settings`,
    `POST /v1/agents/{id}/context/clear`,
    `GET /v1/agents/{id}/pending`,
    `POST /v1/agents/{id}/prompts/{rid}/answer`,
    `POST /v1/agents/{id}/approvals/{rid}/respond`.
  - 32 KiB body limit, 30 accepted requests per agent per hour, 4k payload cap,
    redacted logs.
- CLI under `packages/backend/palimind/cli/`: `pm agent list`, `pm agent run`,
  `pm agent status`, `pm agent set-model`, `pm agent new-chat`, with exit codes
  0/1/2/3/4/5 matching the automation contract.

#### 4.4 Signed webhook routines

- Extend routine triggers with `webhook`: route id, secret, event type, ≤128
  JSON Pointer filters, receipts, 7-day retention, 5-minute timestamp window,
  `sha256=HMAC-SHA256(secret, "<timestamp>.<delivery-id>.<body>")`, constant-time
  compare.
- `POST /api/hooks/{route_id}` with 200 duplicate / 202 accepted / 400/401/403/
  404/413/415/429/503 responses.
- Secret rotation and test-event routes.
- Reuse the existing workflow webhook path where possible; keep the two
  contracts separate so workflow triggers do not change meaning.

**Acceptance**

- Fake-clock scheduler tests cover due/quiet/failed/missed/duplicate runs.
- Flow tests cover fan-out, fan-in, failure skip, restart sweep, and step
  failure isolation.
- Automation security tests cover origin/host refusal, bad token, body limit,
  rate limit, path traversal, and secret redaction.
- Webhook tests cover signature, duplicate delivery, filters, inactive routine,
  and oversized body.
- No live provider or model is used.

---

### Phase 5 — Browser and Computer Use (P2, ~7–9 engineer-weeks)

**Outcome:** agents get a persistent browser and cross-platform desktop control
without weakening PaliMind's SSRF, approval, and audit rules.

#### 5.1 Persistent browser host

- Extract browser lifecycle from `agents/tools/browser/tool.py` into
  `agents/browser/host.py`:
  - one browser process per profile, persistent context directories under
    `~/.palimind/browser/profiles/<id>`;
  - shared profile plus named profiles; per-agent `browser_profile`;
  - tab registry with opener relationships, restore rules, and download
    directory `~/.palimind/browser/downloads`;
  - operation queue per tab, deadlines, focus, and close policy.
- Keep the existing URL safety: http(s) only, block loopback/private/link-local/
  reserved addresses, domain allow/deny lists, and DNS re-resolution before
  navigation.
- Add `browser_tabs` persistence and `browser:*` events.
- Add `browser_takeover` for sign-in/password/OTP/CAPTCHA/passkey and a UI card
  that lets the user complete the step. The agent gets only success/failure and
  never a secret.
- Add field-fill tooling for ordinary forms; refuse hidden/disabled/readonly/
  password/OTP/payment fields.

#### 5.2 Computer Use abstraction

- Define `agents/tools/desktop/driver.py`:
  `status`, `list_apps`, `snapshot`, `find`, `act`, `screenshot`, `launch`,
  `close`, `release_input`.
- Keep the existing Linux AT-SPI backend as `driver_linux_atspi.py`.
- Add platform backends behind the same interface:
  - **Option A (recommended if license permits):** adopt a pinned
    `cua-driver`-style daemon as an optional binary, as OpenBot does.
  - **Option B:** native accessibility adapters on macOS (AXUIElement) and
    Windows (UI Automation), with XTEST/uinput fallback on Linux.
- Keep the current per-agent `desktop_access`/`desktop_control`, app allowlist,
  protected-process refusal list, rate limit, approval for mutating actions,
  append-only audit that never stores typed text, and Stop that releases input.
- Add `desktop_status` capability reporting so the UI can show which backend is
  active.

**Acceptance**

- Browser state tests cover profile creation, tab restore, opener
  relationships, download path, SSRF blocks, and takeover refusal.
- Desktop tests use a fake driver; Linux adapter tests remain as they are.
- A policy test proves an agent cannot read a secret from a takeover card or
  audit log.
- No automated desktop benchmark or live desktop session is required.

---

### Phase 6 — Skills, plugins, MCP, connectors (P2, ~5–7 engineer-weeks)

**Outcome:** skills become portable folders with revisions, MCP servers are
manageable by agents and users, and a plugin catalog can install a tool + its
skills as one unit.

#### 6.1 Skills

- Extend `agents/skills.py` to read both existing JSON/YAML records and the
  Agent Skills folder layout (`<name>/SKILL.md` with YAML frontmatter).
- Write installed skills to `~/.palimind/skills/<slug>/` and, where a workspace
  provider expects them, to the workspace skill folder; record hashes in
  `.palimind/skills-lock.json`; keep disabled skills separately.
- Local library: immutable revisions, create/read/revise/install/list tools,
  protected modified files, update chip.
- Keep the existing marketplace; add install/update/disable/uninstall and
  example-prompt metadata.

#### 6.2 MCP and plugins

- MCP management tools: `list_mcp_servers`, `save_mcp_server`,
  `test_mcp_server`, `set_mcp_server_enabled`, `remove_mcp_server`.
  Test before save; mask headers/env; never return secrets; require approval
  because a server is host-global.
- Plugin catalog: a static JSON catalog with integrity digests; install saves
  the MCP server and pins skills; uninstall reverses both; a local share page or
  deep link is optional and installs nothing by itself.
- API-key requests: `request_api_key`, `list_api_keys`, `remove_api_key`;
  secret form saved under `~/.palimind/agent-api-keys/<agent>/<NAME>` (0600),
  agent gets only name/path, value registered for redaction.
- Connectors (1Password/Bitwarden/GitHub) are **deferred** until a separate
  security review. The plugin/MCP interface leaves room for them.

#### 6.3 Shared agent data namespace

- Add an optional `~/.palimind/shared/data.db` that agents can create/join
  tables in, with a metadata table recording the owning agent; only the owner
  may alter/drop its table. Keep the existing workspace `sqlite_query` tool and
  add `shared_sql_query`/`shared_sql_write` with the same approval gate.
- This adapts OB-31 without making agent-created schemas part of PaliMind's
  migration path: the file is user data, is not migrated on upgrade, and is
  deleted only by an explicit user action.
- Reuse the existing `agents/memory.py` memory 2.0 implementation for OB-32
  (remember/search/forget, essential vs searchable, limits); only add a memory
  editor/limit control if the current UI lacks one.

**Acceptance**

- Skill folder validation, revision immutability, hash-lock update, and
  modified-file protection tests.
- MCP save/test/enable/remove tests with a fake stdio server; no network.
- Plugin install/uninstall is idempotent and removes only managed files.
- Shared-table owner rules and SQL authorizer tests.
- Secret values never appear in tool results, logs, or state.

---

### Phase 7 — Sharing, import/export, templates, visual replies (P2, ~4–6 engineer-weeks)

**Outcome:** agents can produce rich visual answers and move between PaliMind
installations without leaking secrets.

#### 7.1 Visual replies

- `html_render` tool publishes a sandboxed `text/html` artifact above the
  answer; `html_preview` renders a hidden preview and returns a PNG plus height
  and console lines.
- Serve the frame on a dedicated local scheme or a tokenized loopback URL with
  CSP `sandbox allow-scripts allow-forms`; no same-origin access, no
  `window.parent` access, no PaliMind bridge except a small validated message
  API (height, theme, display mode, link, message, context).
- Store the visual as an artifact and a message item type; fall back to the
  title/file for clients that do not support it.
- Reuse the existing artifact panel/export path for PDF/DOCX/PPTX.

#### 7.2 Import/export/transfer

- Define `palimind-import.json` + `agents/<key>/` (profile, skills, routines,
  memories, optional workspace). Version it; accept only optional fields in
  later versions.
- Stage uploads under a single-use token with SHA-256; reject unsafe archive
  paths, symlinks, `.env`, keys, nested archives, and paths outside the
  workspace.
- Export clears secrets, MCP header/env values, provider keys, and URLs with
  credentials; lists what was cleared.
- Import creates agents through the same service as manual creation, rolls back
  an agent whose step fails, and never overwrites an existing workspace file
  without a conflict name.
- Instance transfer = the same archive plus optional settings (providers,
  sections, flows, MCP names); still no secrets.
- Templates: a link-only copy of one local agent (name, title, instructions,
  avatar, routines, skills) with no workspace or memories. Without an account
  service, use a local `.paliagent` file or loopback link; a public share page
  is deferred with Phase 9.

**Acceptance**

- Archive round-trip test: export, import into a clean state DB, compare
  profiles/skills/routines; secrets absent.
- Malicious archive tests: traversal, absolute path, symlink, oversized entry,
  nested archive, duplicate agent name.
- Visual reply sandbox test: a page cannot read PaliMind state or navigate the
  parent.
- No live model is used to generate content; fixtures provide HTML.

---

### Phase 8 — Usage, observability, and diagnostics (P2, ~3–4 engineer-weeks)

**Outcome:** users can see local token/cost usage and diagnose agent problems
without telemetry.

- `agents/usage.py`: aggregate `usage_records` by agent/day/provider/model;
  expose `GET /api/agents/{id}/usage` and `GET /api/usage?from&to&agent`.
- Persist per-stage usage already emitted by the runtime (classifier, planning,
  agent, verification, followups) and add provider-level records.
- Add a **Usage** view with 7/30/90/custom ranges, per-agent rows, provider
  split, and a host-wide summary. Estimate cost from configurable per-million-
  token prices; unknown prices stay unpriced.
- Add local diagnostics export (JSON) with redaction and no chat content by
  default; include versions, provider status, recent errors, feature flags.
- Extend `metrics.py` with task/mailbox/channel/flow/automation counters.
- Optional resource sampling (CPU/RAM/event-loop) stored locally only; no
  upload.

**Acceptance**

- Aggregation tests with fixed timestamps/time zones.
- Cost tests for known/unknown models and cache/context tiers.
- Diagnostics test proves secrets and message text are absent.
- Metrics endpoint remains local and unauthenticated only as today (or behind
  the same token).

---

### Phase 9 — Remote host, web/mobile, Team API (P3, ~10–14 engineer-weeks; deferred)

**Outcome (if approved later):** a PaliMind host can be used from another
device without moving chats/files off the host.

This phase is intentionally after local parity. It should be a separate design
because PaliMind has no account service and no WebRTC layer today.

- Define a versioned remote API with capability negotiation, not one large
  schema.
- Prefer a local-network/Tailscale + bearer-token model first; an account
  service is optional and must remain outside the chat/file path.
- Add remote chat, agent list, tasks, channels, approvals, file transfer, and a
  responsive web client. A native mobile app is a separate product decision.
- Add remote browser live view/control (OB-147) over the same authenticated
  channel: stream a tab, take/release control, stop a page load, and relay a
  host-side sign-in. Never send page credentials to the client.
- Add per-agent member roles `none`/`view`/`chat`/`manage` (OB-226) once
  membership exists; roles gate visibility and writes, not provider access.
- Reuse the existing `/client` page and `/v1` token; add SSE replay and
  resumable streams before adding mobile.
- Keep every remote capability additive and behind the existing token; never
  expose secrets, provider keys, or raw workspace paths.

**Acceptance**

- Contract tests for each capability, auth, replay, and version negotiation.
- No chat content leaves the host except to an authenticated client.
- This phase is not started until Phases 0–5 pass their acceptance gates.

---

## 7. API and event contract summary

### 7.1 New HTTP surfaces

| Prefix | Purpose |
|---|---|
| `/api/agents/{id}/tasks` | Task lanes and task conversation. |
| `/api/agents/{id}/messages` | Mailbox send. |
| `/api/agents/{id}/deliveries/{id}` | Delivery status/answer. |
| `/api/agents/{id}/interrupt` | Safe interruption. |
| `/api/agents/{id}/pending` | Prompts, approvals, takeovers. |
| `/api/agents/{id}/waits` | Event waits. |
| `/api/agents/{id}/sections` | Sidebar sections. |
| `/api/agents/{id}/usage` | Local usage. |
| `/api/channels` | Channel CRUD, messages, tasks, lifecycle. |
| `/api/providers` | Provider status, models, accounts, runtime, sign-in. |
| `/api/browser` | Profiles, tabs, takeover. |
| `/api/usage` | Host-wide usage. |
| `/api/import`, `/api/export`, `/api/transfer` | Archive flows. |
| `/api/hooks/{route_id}` | Signed routine webhooks. |
| `/api/routines/calendar.ics` | Local calendar feed. |
| `127.0.0.1:<automation-port>/v1/...` | Local scripts API (separate listener). |

Existing routes keep their URLs and payload meaning. Extend only with optional
fields.

### 7.2 New SSE/event names

`provider:status`, `provider:models`, `provider:usage`, `provider:model-changed`,
`agent:task`, `agent:task-conversation`, `agent:task-delta`,
`agent:queue`, `agent:delivery`, `agent:interrupted`, `agent:hidden`,
`channel:changed`, `channel:message`, `channel:task`, `channel:receipt`,
`wait:opened`, `wait:woken`, `routine:quiet`, `routine:failed`,
`routine:flow`, `browser:tab`, `browser:takeover`, `usage:updated`.

All events go through `events/store.py` and `events/hub.py`; every stream keeps
a monotonic id and honors `Last-Event-ID`.

---

## 8. Frontend plan

Reuse the existing Agents workspace and primitives; do not create a second app.

| Area | Work |
|---|---|
| Agents home | Live task card, queue holds, delivery status, usage chip. |
| Tasks | Task list, task conversation, Send/Stop/Close/Reopen/Run as task. |
| Channels | Channel list, transcript with authors, member avatars, task owner, settings, archive/restore. |
| Providers | Settings → Providers: install/update, sign-in, accounts, model list, default model, backup order. |
| Browser | Persistent browser panel with profiles, tabs, downloads, takeover card. |
| Skills/plugins | Installed/available skills, revisions, update chip, plugin catalog. |
| Import/export | File pickers, preview, conflict warnings, cleared-secret list. |
| Usage | Range picker, per-agent/provider chart, unpriced markers. |
| Visual replies | Sandboxed iframe/frame with height/theme messages, fallback title/file. |

Frontend files:

- `packages/frontend/src/api.ts`: typed calls for the new routes.
- `packages/frontend/src/features/agents/AgentsWorkspace.tsx`: add views.
- new `features/channels/`, `features/tasks/`, `features/providers/`,
  `features/usage/`, `features/browser/`.
- `features/agents/types.ts`: new fields.
- `AgentWizard.tsx`/`Inspector.tsx`: provider, task limit, automation, browser
  profile, backup models, sections.
- `AgentsInbox.tsx`: pending prompts and takeovers in one inbox.

UI acceptance uses existing render/reducer tests and typecheck; no model.

---

## 9. Security and privacy requirements

These are gates, not suggestions.

1. **Local-first.** No telemetry, no analytics upload, no implicit cloud call.
   Provider network use happens only when the user configures that provider and
   runs a turn.
2. **Secrets.** Provider keys, MCP headers/env, automation tokens, and API keys
   live outside SQLite and outside prompts. They are `0600` files or the OS
   secret store, registered for redaction, and never returned by an API/tool.
3. **Automation listener.** Loopback only; refuse `Origin` and foreign `Host`
   before token check; per-agent rate limit; body/size limits; token file paths
   only in prompts.
4. **Browser.** Keep SSRF blocks and domain policy; tool actions stay tiered and
   approval-gated; takeover is the only path for passwords/OTP/CAPTCHA/passkeys;
   no secret reaches the model or audit log.
5. **Desktop.** Keep the protected-process list, app allowlist, per-agent
   access/control flags, approval for mutations, rate limit, and append-only
   audit with no typed text.
6. **Approvals.** Agents may restrict access for themselves/teammates but may
   never widen it. Only the user moves an agent to a broader access level or
   enables automation.
7. **Remote (Phase 9).** Bearer token, capability negotiation, redaction, and no
   chat/file content in any account service. Prefer local network/VPN over a
   public relay.
8. **Migrations.** Preserve every shipped state schema; test an old DB with a
   copy, never mutate the user's only copy.
9. **Redaction tests.** Every new log/export/send path gets a test with a fake
   secret and a negative assertion.

---

## 10. Testing strategy (no model tests, no benchmarks)

The instruction for this task is explicit: **do not test models and do not run
model benchmarks.** The plan therefore uses deterministic fakes and protocol
fixtures.

### 10.1 Test layers

| Layer | What it proves | Tools |
|---|---|---|
| Provider contract | Event normalization, cancel, error, usage, session resume | `tests/fakes/provider.py` |
| ACP protocol | JSON-RPC framing, initialize, session/new, stream, tool, permission, close | `tests/fixtures/acp_server.py` |
| Task/mailbox | Lane limits, holds, idempotency, crash recovery, states | state DB fixtures |
| Channels | Deterministic routing, revisions, idempotent commands, archive/restore | fake agents |
| Routines/flows | Due runs, quiet/failed, fan-in/fan-out, restart sweep | fake clock |
| Waits/automation | Wake matching, origin/host/token, limits, redaction | test HTTP client |
| Webhooks | Signature, filters, duplicates, retries, oversized body | HMAC fixtures |
| Browser | Profiles, tabs, SSRF, takeover refusal, download path | fake browser host |
| Desktop | Driver interface and policy; Linux adapter unchanged | fake driver |
| Skills/plugins | Folder validation, revisions, hash lock, install/uninstall | temp dirs |
| Import/export | Round trip, traversal/symlink/secret rejection | archive fixtures |
| Usage | Day/timezone aggregation, unknown pricing | fixed records |
| Security | Redaction, path traversal, token scope, sender checks | negative fixtures |
| UI | Reducers/render smoke/typecheck | existing frontend tests |

### 10.2 Commands to run

- `make backend-test` (the suite must not require Ollama for new tests).
- `pytest packages/backend/tests/test_provider_contract.py ...` for focused tests.
- `make frontend-test` / `npm run build` for UI typecheck.
- `make lint` and `make typecheck` for changed modules.

### 10.3 Commands explicitly **not** run for this work

- `make agent-benchmark`
- `make agent-benchmark-live`
- `make agent-benchmark-vs-grok`
- `make routing-probe`
- `make desktop-dogfood`
- Any pytest that starts Ollama/OpenCode/a real provider or asserts model
  quality.

Model quality is out of scope. A passing deterministic suite proves the
contracts, persistence, policy, and UI wiring, not model intelligence.

---

## 11. Sequencing, estimates, and dependencies

Estimates are rough engineer-weeks for one experienced backend/frontend pair;
they exclude review and release overhead.

| Phase | Scope | Estimate | Depends on |
|---|---|---|---|
| 0 | Provider boundary, threads, migrations, fake provider | 2 | — |
| 1 | Tasks, mailbox, profile/section/hidden tools, UI | 5 | 0 |
| 2 | ACP/Codex/Claude/OpenCode/OpenAI-compatible providers, runtime manager, failover | 8–10 | 0 |
| 3 | Channels, deterministic routing, channel tasks/UI | 6–8 | 1 |
| 4 | Routines/flows/waits/automation/webhooks/calendar | 7–9 | 1 |
| 5 | Browser host/profiles/takeover; desktop driver abstraction | 7–9 | 0/1 |
| 6 | Skills folders/library, plugins, MCP management, API keys | 5–7 | 1 |
| 7 | Visual replies, import/export/transfer/templates | 4–6 | 1/6 |
| 8 | Usage, metrics, diagnostics | 3–4 | 1/2 |
| 9 | Remote host/web/mobile/Team API | 10–14 | 1–5 |

**Critical path:** Phase 0 → Phase 1 → Phase 3/4. Phase 2 can run in parallel
with Phase 1 after Phase 0. Phase 5 can start after Phase 0. Phase 6/7 can start
after Phase 1. Phase 9 waits.

**Suggested milestones**

- M1 (Phase 0–1): tasks, mailbox, profile tools, hidden agents, sections.
- M2 (Phase 2): one real external provider (Codex or OpenCode) plus ACP.
- M3 (Phase 3–4): channels and automation; this is the "work with a team"
  milestone.
- M4 (Phase 5–6): browser/desktop and ecosystem.
- M5 (Phase 7–8): sharing, visual replies, usage.
- M6 (Phase 9, optional): remote/mobile.

---

## 12. First PR-sized tasks

These are intentionally small and independently reviewable.

1. **Provider protocol skeleton** — `agents/providers/base.py`,
   `agents/providers/registry.py`, `agents/providers/ollama.py`; adapt one call
   site; add `tests/fakes/provider.py` and contract tests.
2. **Thread/migration foundation** — add `agent_threads`/`provider_sessions` to
   `state_store.py`; migrate existing agents to a chat thread; add a legacy DB
   test.
3. **Task store** — `agents/tasks.py` CRUD, limits, lane status; API and tests;
   no UI yet.
4. **Mailbox store** — deliveries, states, idempotency, holds; API and tests.
5. **Queue lane extension** — `lane`/`task_id`/`hold_reason` in queue items;
   per-lane busy checks; crash recovery tests.
6. **Task tools** — `start_task`, `send_message`, `interrupt_agent`,
   `list_agents`, `read_agent`; tool schema/approval tests.
7. **Tasks UI** — Tasks tab, task conversation, actions, live card.
8. **Profile tools** — `create_agent`, `update_profile`, `update_agents`,
   `list_models`, sections; validation and "never widen access" tests.
9. **ACP client** — JSON-RPC framing, session lifecycle, fixture server tests.
10. **Codex adapter** — captured-transcript fixture tests; no live CLI.
11. **Channel store** — tables, service, deterministic routing tests.
12. **Channel UI** — transcript, member list, task owner, archive/restore.
13. **Wait store + `await_event`** — wake matching and limits.
14. **Automation server** — token files, origin/host checks, routes, rate limit.
15. **Routine flow store/runtime** — fan-out/fan-in and restart tests.
16. **Browser host extraction** — profile/tab state behind the existing tools.
17. **Desktop driver interface** — fake driver tests; Linux adapter unchanged.
18. **Skill folder support + local revision library** — migration and tools.
19. **Visual reply** — sandboxed HTML artifact and frame.
20. **Usage aggregation + view** — records, API, chart.
21. **Subagent + side-question plumbing** — per-turn registry, API, UI row.
22. **Shared data namespace** — owner rules, SQL authorizer, tools.

---

## 13. Traceability matrix

| Inventory IDs | Phase | Acceptance evidence |
|---|---|---|
| OB-20–OB-29 | 1, 7 | Task/profile/section/hidden tests; import/export round trip |
| OB-40–OB-56 | 2 | ACP fixture; provider contract; runtime manager; failover tests |
| OB-60–OB-67 | 1 | Lane/hold/idempotency/recovery tests |
| OB-80–OB-85 | 1, 3 | Delivery/interrupt/reaction/side-question tests; delegation policy prompt |
| OB-90–OB-97 | 3 | Routing table, revision, archive/restore tests |
| OB-110–OB-121 | 4 | Fake-clock routine, flow, wait, automation, webhook tests |
| OB-140–OB-147 | 5, 9 | Browser profile/tab/SSRF/takeover tests; remote live view in Phase 9 |
| OB-160–OB-163 | 5 | Driver interface and policy tests; remote desktop deferred |
| OB-180–OB-187 | 6 | Skill/plugin/MCP/API-key tests; connectors deferred |
| OB-200–OB-204 | 7 | Visual sandbox and attachment tests |
| OB-220–OB-226 | 9 | Remote contract, live-view, and role tests (deferred) |
| OB-30–OB-32 | 1, 6 | Subagent, side-question, shared-table, memory tests |
| OB-13 | — | Rejected/deferred; no work |
| OB-09 (agent part) | 8 | Usage aggregation/diagnostics tests |
| OB-240–OB-246 | all | Redaction/path/token/approval negative tests |

---

## 14. Open decisions

These need a product decision before or during implementation:

1. **Provider licensing and distribution.** Which external CLIs may PaliMind
   bundle or download? Prefer system-installed CLIs first, managed downloads
   only with a permissive license and pinned digests.
2. **Computer Use driver.** Adopt a `cua-driver`-style third-party binary
   (fast, cross-platform) or build native accessibility adapters (more control,
   more work). Phase 5 should start with an interface and a Linux adapter.
3. **Channels vs teams.** Keep both: teams are explicit multi-agent runs,
   channels are shared group chats. If the UI becomes confusing, merge them
   later behind one "Groups" view.
4. **Public templates/share links.** Without an account service, use local
   `.paliagent` files or loopback links. Public links wait for Phase 9.
5. **Remote/mobile.** Keep deferred unless a concrete user need justifies the
   account/transport layer.
6. **Telemetry.** Keep zero. Usage analytics are local only; diagnostics are
   user-initiated local exports.

---

## 15. Implementation status (this pass)

This section records what the first implementation pass actually shipped. It
does not claim that every phase is complete.

### 15.1 Shipped

| Phase | Delivered | Key files |
|---|---|---|
| 0 | Provider protocol, fake provider, Ollama and OpenAI-compatible adapters, ACP client, provider presets, durable threads/sessions, usage records, feature flags, schema v2 tables | `agents/providers/*`, `agents/threads.py`, `storage/state_store.py`, `settings.py` |
| 1 | Task lanes, mailbox deliveries/events/reactions, sections, hidden agents, task/mailbox/section/side-question APIs, task/mailbox/profile tools, task UI | `agents/tasks.py`, `agents/mailbox.py`, `agents/sections.py`, `agents/task_tools.py`, `agents/tasks_api.py`, `features/agents/work/TasksView.tsx`, `features/agents/AgentsInbox.tsx` |
| 2 | Concrete Codex App Server and Claude stream-json adapters with transcript fixtures; generic ACP; Ollama/OpenAI-compatible; presets; failover gate wired into the worker call path | `agents/providers/codex.py`, `agents/providers/claude.py`, `agents/providers/jsonl.py`, `agents/failover.py`, `llm/mixture_of_expert/agents.py`, `tests/test_provider_codex_claude.py` |
| 3 | Channel store, deterministic routing, channel tasks/revisions, archive/restore, channel tools, channel API/UI | `agents/channels.py`, `agents/channel_tools.py`, `agents/channels_api.py`, `features/agents/ChannelChat.tsx`, `features/agents/ConversationRail.tsx` |
| 4 | Waits, automation listener/token files/security tests, routine quiet/failure signals, routine flows, flow tools, calendar feed, signed routine webhooks with receipts/filters, `pm agent` CLI | `agents/waits.py`, `agents/automation.py`, `agents/flows.py`, `agents/webhooks.py`, `agents/routine_tools.py`, `agents/flows_api.py`, `agents/webhooks_api.py`, `cli/commands.py` |
| 5 | Browser profiles/tabs/takeover state and API, persistent Playwright profile launch, managed tab tools, desktop driver interface | `agents/browser_profiles.py`, `agents/tools/browser/tool.py`, `agents/tools/desktop/driver.py` |
| 6 | Agent Skills folder support, immutable local skill library, plugin catalog/install, MCP management tools, API-key tools | `agents/skills.py`, `agents/skills_library.py`, `agents/plugins.py`, `agents/mcp_tools.py`, `agents/secrets_tools.py` |
| 7 | Agent export/import/archive, templates, sandboxed visual replies and tools/API | `agents/sharing.py`, `agents/sharing_api.py`, `agents/visuals.py`, `agents/visual_tools.py` |
| 8 | Local usage records/aggregates, usage API and UI, provider status API/UI | `agents/usage.py`, `agents/usage_api.py`, `agents/providers_api.py`, `features/agents/SettingsDrawer.tsx`, `features/agents/work/OverviewView.tsx` |

### 15.2 Still open

- Provider-account UI and the remaining provider-specific settings forms
  (backend data fields and model catalog exist).
- Full browser-live-view/remote control and remote desktop. Local profiles,
  tabs and takeover state exist; streaming is Phase 9.
- 1Password/Bitwarden/GitHub connectors and remote sign-in relays.
- Remote host/Team API/mobile client. This remains deferred by design.
- Frontend import/export dialogs and provider sign-in forms.
- Connector tools: the empty gmail/calendar/slack/drive/sheets folders were
  removed rather than shipped as unavailable tools.
- Edit-before-run approvals and the typed tool-UI contract are shipped; the
  broader connector catalog is not.

### 15.3 Verification

- Backend: `python -m pytest -m "not integration" -q` → **713 passed, 2 skipped,
  6 deselected**.
- Frontend: `npm test` → **147 passed** plus the render smoke suite; `npx tsc -b`
  → clean; `npm run build` → success.
- New regression files: `test_agent_tasks_mailbox.py`,
  `test_provider_acp.py`, `test_provider_codex_claude.py`,
  `test_agent_channels.py`, `test_agent_automation_flows.py`,
  `test_agent_ecosystem.py`, `test_agent_api.py`, `test_agent_webhooks.py`.
- No model was started, tested, or benchmarked.

---

## 16. Definition of done

A phase is done only when:

- its deterministic tests pass without a model, network, or live provider;
- the migration test preserves an old state DB;
- new routes/tools are documented in code and guarded by the existing token/
  approval/redaction rules;
- the UI has a typecheck and a reducer/render test where it changed;
- no secret appears in logs, exports, prompts, or test fixtures;
- the feature is behind a flag until its acceptance gate passes;
- the existing PaliMind features (RAG, knowledge graph, documents, data tools,
  image generation, research, memory, OpenAI-compatible API) still pass their
  tests;
- no model benchmark or live model test was run as part of the work.
