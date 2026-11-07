# OpenBot feature inventory

This document records the feature review of `~/openbot` that feeds
[`openbot-agents-implementation-plan.md`](openbot-agents-implementation-plan.md).
It is an inventory, not a commitment to copy every feature into PaliMind.

- Reviewed: 2026-11-07
- Source tree: `~/openbot` (OpenBot, a local-first Electron desktop workspace for
  persistent AI teammates)
- Method: read the product README and architecture documents, then confirmed the
  important behaviours in source directories and package manifests.
- No model was started, tested, or benchmarked for this review.

## How to read the IDs

Each row has a stable ID (`OB-nn`) that the implementation plan uses in its gap
matrix and traceability table. "Evidence" names the document or source area that
describes the feature. A feature described only in a design document is marked
"(design)".

**Path convention:** every unqualified path in this inventory is relative to
`~/openbot`. The PaliMind baseline paths in the implementation plan are relative
to the PaliMind repository.

---

## 1. Product and application surfaces

| ID | Feature | What OpenBot does | Evidence |
|---|---|---|---|
| OB-01 | Desktop application | Electron app for macOS 13+, Windows 10+, and Linux AppImage; renderer is sandboxed and talks to main over a typed preload bridge. | `README.md` (Install, Architecture); `docs/architecture/structure.md` |
| OB-02 | Public web client | `/app` served by the account Worker; mounts the shared workspace UI over a WebRTC/HTTP host connection. | `docs/architecture/browser.md` (Browser client); `docs/web-client.md` |
| OB-03 | Mobile app | Expo/React Native iPhone and Android client for remote hosts: chat, channels, tasks, marketplace, browser, notifications, Live Activities, app lock, sharing. | `apps/mobile/src/features/*`; `apps/mobile/README.md` |
| OB-04 | Self-hosted / headless server | Runs OpenBot as an always-on server (systemd, Docker, ECS, Nix) with `openbot login`, remote desktop, and hosted-server options. | `README.md` (Linux server, Docker, Nix); `docs/self-hosted-server.md`; `docs/aws-ecs.md` |
| OB-05 | Accounts and teams | Optional email-code accounts on Cloudflare Workers + D1; memberships, invitations, roles, logical sessions, team hosts. | `README.md`; `docs/architecture/servers.md`; `apps/auth-api` |
| OB-06 | Billing and plans | Stripe subscriptions, plan limits, hosted-server plans, commercial licensing. | `docs/architecture/servers.md` (Billing) |
| OB-07 | Hosted sites and storage | Publishes private sites per server; storage usage, disk checks, cleanup, file ownership. | `docs/architecture/servers.md` (Storage, Hosted sites) |
| OB-08 | Public status page and status webhooks | Status page plus signed incident/maintenance webhooks for the team. | `docs/status-webhooks.md`; `apps/status` |
| OB-09 | Product analytics | OpenPanel for mobile and website; local numeric agent usage analytics; per-agent and host-wide token/cost dashboards over 7/30/90/custom days; resource sampling. | `docs/architecture/analytics.md` (Agent usage analytics, Host-wide Usage, Resource sampling) |
| OB-10 | Internationalization | English, French, Japanese, Brazilian Portuguese, Turkish catalogs shared by desktop, web, mobile. | `docs/i18n.md`; `packages/i18n` |
| OB-11 | Release / update / packaging | Tag-driven signed releases, auto-update, AppImage/DMG/NSIS, Docker, Nix, ECS; provider runtime pinning. | `README.md` (Releases, Nix, Docker); `docs/RELEASING.md` |
| OB-12 | Local-first data boundary | Local SQLite is the source of truth; providers and visited pages can use the network; cloud stores only accounts and membership data. | `README.md` (Local data and network boundaries); `AGENTS.md` (Product constraints) |
| OB-13 | Multi-tenant macOS hosting | Host Manager/Host PKG runs one Standard macOS user per tenant, with setup, verify, status/watch, and shared-application upgrades. | `docs/architecture/servers.md` (macOS Host Manager); `README.md` (Shared macOS hosts) |

---

## 2. Agent model and lifecycle

| ID | Feature | What OpenBot does | Evidence |
|---|---|---|---|
| OB-20 | Persistent agents | Each agent has its own workspace, conversation, profile, provider session, settings, memory, and identity that survive provider switches and restarts. | `README.md` (What works); `docs/architecture/agents.md` |
| OB-21 | Prompt-driven profiles | Agents create and edit agents with tools: `create_agent`, `update_profile`, `update_agents`, `read_agent`, `list_agents`, `list_models`, avatars, titles, instructions, sections. | `docs/architecture/agents.md` (Prompt-driven agent profiles); `src/backend/openbot-tools.ts` |
| OB-22 | Agent sections | Flat sidebar sections with list/create/rename/delete/assign tools and persisted layout. | `docs/architecture/agents.md` (Prompt-driven agent profiles); `src/backend/agent/sidebar-tools.ts` |
| OB-23 | Hidden agents | Hide instead of delete; keeps workspace/history/memory; refuses messages, routines, mentions, and queue work until restored. | `docs/architecture/agents.md` (Hidden agents) |
| OB-24 | Per-agent settings | Model, reasoning effort, provider account, access level, Computer Use, notifications, busy-message mode, browser profile, panel state, backup models. | `README.md`; `docs/architecture/agents.md`; `docs/architecture/providers.md` |
| OB-25 | Conversation context management | Context monitoring and automatic compaction before the provider window is exhausted; handoff on provider change. | `README.md`; `docs/architecture/providers.md` (Compaction ownership, History retrieval) |
| OB-26 | Agent duplication / templates | Duplicate an agent; publish a link-only template with name, title, instructions, avatar, routines, and skills; unpublish keeps the link. | `docs/architecture/agents.md` (Agent templates) |
| OB-27 | Agent import | Import a `.zip` export (`openbot-import.json` + agent folders) with skills, routines, memories, channels; staged and checksum-verified. | `docs/architecture/agents.md` (Agent import); `docs/architecture/servers.md` (Agent import) |
| OB-28 | Instance transfer | Export/import all agents and selected settings to another OpenBot server in one `.zip`; secrets are cleared. | `docs/architecture/agents.md` (Instance transfer); `docs/architecture/servers.md` (Instance transfer) |
| OB-29 | Agent deletion lifecycle | Deletes workspace, generated attachments, deliveries, usage, receipts; keeps shared transfers used by other agents. | `docs/architecture/structure.md` (State ownership); `src/backend/agent/agent-removal.ts` |
| OB-30 | Subagents | An agent starts child agents inside one turn; their lists and results appear in the conversation and cross the Team API. | `docs/architecture/servers.md` (Subagents); `packages/contracts/src/team-protocol/subagents-v1.ts` |
| OB-31 | Shared agent data tables | Agents share one SQLite namespace (`~/OpenBot/Shared/Data/agent-data.db`) for cross-agent tables, with creator-only alter/drop. | `docs/architecture/structure.md` (State ownership) |
| OB-32 | Agent memories | Per-agent `remember`, `search_memories`, `forget_memory`; essential vs searchable retention; per-agent memory limit; memory editor. | `docs/architecture/providers.md` (Built-in tool discovery); `docs/architecture/servers.md` (Admin capabilities); `src/backend/agent/agent-memories.ts` |

---

## 3. Provider harnesses and models

| ID | Feature | What OpenBot does | Evidence |
|---|---|---|---|
| OB-40 | Codex harness | Local Codex App Server over stdio JSONL; developer instructions, dynamic tools, session resume, history read. | `README.md`; `docs/architecture/providers.md`; `src/backend/app-server-client.ts` |
| OB-41 | Claude harness | Claude Agent SDK session over stream JSON; SDK MCP bridge, `AskUserQuestion`, usage. | `README.md`; `docs/architecture/providers.md`; `src/backend/claude-client.ts` |
| OB-42 | Grok harness | Grok CLI with xAI login and billing hooks, ACP transport. | `docs/architecture/providers.md` (OpenCode and ACP); `src/backend/grok-client.ts` |
| OB-43 | OpenCode harness | Managed/pinned OpenCode 2 CLI over ACP; Free and paid (Go) model catalogs; key handling. | `docs/architecture/providers.md` (OpenCode and ACP) |
| OB-44 | Gemini harness | Google Antigravity ACP server, browser sign-in, model/capability handling. | `docs/architecture/providers.md` (Gemini) |
| OB-45 | Cursor harness | Cursor CLI (`cursor-agent acp`), sign-in or API key. | `docs/architecture/providers.md` (Cursor) |
| OB-46 | Cline harness | Cline CLI (`cline --acp`), sign-in or API key, free-model behavior. | `docs/architecture/providers.md` (Cline) |
| OB-47 | Other ACP agents | Pi, Muse, and custom ACP agents; registry of installable ACP agents with staged downloads and integrity checks. | `docs/architecture/providers.md` (Pi, Muse, Custom agents, ACP registry) |
| OB-48 | Custom OpenAI-compatible endpoints | User-defined endpoint, key, headers, model list; local endpoint editing. | `docs/architecture/providers.md` (Local detection and endpoint edit) |
| OB-49 | Local model-server detection | Detects Ollama and LM Studio, installed agent CLIs, and edits local endpoints. | `README.md`; `docs/architecture/providers.md` |
| OB-50 | Provider runtime management | Downloads and pins provider CLIs per platform, checks digest/paths, prefers managed copy, offers updates, waits for active turns, keeps the user's system CLI. | `docs/architecture/providers.md` (Provider CLI updates, Managed provider updates) |
| OB-51 | Model catalog and efforts | Per-provider model list, reasoning efforts, default model, model picker, auto/free labels, model name normalization. | `docs/architecture/providers.md` (Model catalog); `src/backend/agent/model-catalog.ts` |
| OB-52 | Provider accounts | Multiple accounts per provider, account state, sign-in per account, account-scoped sessions and usage. | `docs/architecture/providers.md`; `src/backend/agent/provider-accounts.ts` |
| OB-53 | Usage limits and failover | Plan usage limits hold queues; backup model order moves an agent on a limit or provider error and returns it after recovery. | `docs/architecture/providers.md` (Backup models and failover) |
| OB-54 | Usage reset credits | Codex reset credits read and consumed through provider methods; refreshes usage and releases held agents. | `docs/architecture/providers.md` (Usage reset credits) |
| OB-55 | Provider-specific settings | Validated per-provider overrides, ACP settings, reset markers, capability reporting. | `docs/architecture/providers.md` (Provider settings and the ACP registry) |
| OB-56 | Inception provider | Local-only provider on Pi's managed CLI with Mercury models and API-key sign-in. | `docs/architecture/providers.md` (Inception) |

---

## 4. Work scheduling: queues, mailbox, tasks

| ID | Feature | What OpenBot does | Evidence |
|---|---|---|---|
| OB-60 | FIFO queue | Per-agent FIFO message queue with pause, resume, cancellation, holds, and crash-safe persistence. | `README.md` (What works); `docs/architecture/agents.md`; `src/backend/agent/drain-scheduler.ts` |
| OB-61 | Mailbox deliveries | Durable delivery records with status (`queued`/`starting`/`running`/`completed`/`failed`/`interrupted`/`cancelled`), retry keys, answers, errors. | `docs/automation.md` (Routes); `src/backend/agent/mailbox-sync.ts` |
| OB-62 | Queue holds | Holds with reasons such as `task-limit`, `agent-restarting`, `usage-limit`, `server-busy`, `agent-busy`, `one-turn`, `hidden`. | `docs/architecture/agents.md` (Agent tasks) |
| OB-63 | Agent tasks | Separate execution threads of one agent; own provider thread, conversation, queue lane, progress, result, error, limit, close/reopen. | `docs/architecture/agents.md` (Agent tasks) |
| OB-64 | Task tools | Agent starts tasks with `start_task`; up to 8 open tasks started by the agent and 50 open tasks total. | `docs/architecture/agents.md` (Agent tasks) |
| OB-65 | Task UI and remote | Tasks tab, "Run as task", task conversation, Stop/Close/Reopen; remote capability `agent-tasks-v1`. | `docs/architecture/agents.md` (Agent tasks); `apps/mobile/src/app/(app)/server-tasks.tsx` |
| OB-66 | Busy-message modes | A message to a running agent waits or steers when the provider supports native steering. | `docs/architecture/agents.md` (Agent tasks); `docs/architecture/providers.md` |
| OB-67 | Crash recovery | Boot recovery resumes queued tasks, routine runs, and deliveries; interrupted runs are marked. | `docs/architecture/agents.md`; `src/backend/agent/boot-recovery.ts` |

---

## 5. Agent-to-agent communication

| ID | Feature | What OpenBot does | Evidence |
|---|---|---|---|
| OB-80 | Agent messages | Agents send messages, replies, reactions, images, and managed file transfers to other agents. | `README.md` (What works); `src/backend/agent/delivery-content.ts` |
| OB-81 | Delegation policy | Shared developer instructions: delegate when a teammate owns the work, report blockers, no acknowledgement loops, reply with Status/Result/Evidence/Unblock. | `docs/architecture/agents.md` (Agent communication policy) |
| OB-82 | Agent status and interruption | `list_agents` exposes status, queues, turn times; `interrupt_agent` stops only the caller's request and records why. | `docs/architecture/agents.md` (Agent communication policy); `src/backend/agent/agent-interrupt-tool.ts` |
| OB-83 | Multiple request copies | Answers wait while another teammate's copy of the same request is active; the last copy releases one combined turn. | `docs/architecture/agents.md` (Agent communication policy) |
| OB-84 | Reactions | Agents react to user messages. | `src/backend/openbot-tools.ts` (`react_to_user_message`) |
| OB-85 | Side questions | A member asks an agent an ephemeral question grounded in its chat; the exchange is not added to the conversation. | `docs/architecture/servers.md` (Side questions) |

---

## 6. Shared channels (group chats)

| ID | Feature | What OpenBot does | Evidence |
|---|---|---|---|
| OB-90 | Channels | Shared group chats with one host, purpose, participating agents, selected lead, linked conversations, stable message IDs, per-channel sequence. | `docs/architecture/channels-and-messaging.md` (Shared channel chats) |
| OB-91 | Deterministic routing | One owner is selected by recipient, task, reply, sole open task, or sole available member without a model; otherwise the lead routes in a separate session. | `docs/architecture/channels-and-messaging.md` |
| OB-92 | Channel tasks | Task ownership, child tasks, up to eight automatic assignments, two active assignments per channel, revisions, transfer ownership. | `docs/architecture/channels-and-messaging.md` |
| OB-93 | Channel controls | Stop, Resume, Reassign, Archive, Restore; per-channel read positions; deleted-channel restore; no Pause/Resume controls. | `docs/architecture/channels-and-messaging.md` |
| OB-94 | Channel tools | History, assign child task, transfer ownership, report result, add/remove member, set instructions, list/create/update/delete routines. | `docs/architecture/channels-and-messaging.md` |
| OB-95 | Channel memory and context | Bounded self-contained context packet per turn, versioned summary, channel memories, source message IDs. | `docs/architecture/channels-and-messaging.md` |
| OB-96 | Channel attention | Approvals, questions, plan cards, and browser steps of member threads appear in the channel; screen capture always asks. | `docs/architecture/channels-and-messaging.md` |
| OB-97 | Channel remote/mobile | `channel-chats-v1`, `channel-attention-v1`, `channel-delete-v1` capabilities; mobile channel UI and caches. | `docs/architecture/channels-and-messaging.md` |

---

## 7. Routines, flows, waits, and automation

| ID | Feature | What OpenBot does | Evidence |
|---|---|---|---|
| OB-110 | Routine scheduling | Scheduled agent and channel routines with active/paused state, missed-run policies, run history, limits. | `docs/architecture/agents.md` (Scheduled routine changes); `docs/automation.md` |
| OB-111 | Quiet routine runs | A routine can end with `[[no-update]]` or the `routine_no_update` tool; quiet runs do not count as unread, notify, or reach remote clients. | `docs/architecture/agents.md` (Quiet routine runs) |
| OB-112 | Failed routine runs | `routine_report_failure` records a redacted reason and marks the run failed while keeping the answer. | `docs/architecture/agents.md` (Failed routine runs) |
| OB-113 | Routine sessions | A routine run gets its own ephemeral provider session with a short handoff, then a digest is appended to the chat session. | `docs/architecture/agents.md` (Routine sessions) |
| OB-114 | Routine calendar feed | Loopback iCalendar feed for the next 30 days of active routines, token in the path, no cloud calendar access. | `docs/architecture/agents.md` (Routine calendar feed) |
| OB-115 | Routine flows | JSON canvas/DAG that hands a routine's answer to other agents; links, node positions, steps, fan-in, failure skip. | `docs/architecture/agents.md` (Routine flows); `src/backend/routine-flows/` |
| OB-116 | Routine-flow tools | `list_routine_flows`, `connect_routine_agents`, `disconnect_routine_agents`. | `docs/architecture/agents.md` (Routine flows) |
| OB-117 | Agent waits | `await_event`, `list_waits`, `close_wait`; at most 20 open waits per agent; a routine or script run wakes a wait. | `docs/automation.md`; `src/backend/agent-waits/` |
| OB-118 | Local scripts API | Loopback HTTP server, per-agent opt-in, token files (0600), origin/host refusal, rate limits, message/run/delivery/settings/context/pending/answer/approval routes. | `docs/automation.md`; `docs/architecture/agents.md` (Local scripts API) |
| OB-119 | Automation CLI | `openbot-cli` list/run/status/agent set-account/set-model/new-chat with exit codes and `--wait`. | `docs/automation.md` (Command line) |
| OB-120 | Webhook routines | Signed webhook trigger with event type, up to 128 JSON Pointer filters, receipts, duplicate suppression, retries, test events, secret rotation. | `docs/architecture/events.md`; `docs/webhooks.md` |
| OB-121 | Routine recovery | Missed-run policies and recovery capability for remote editors. | `docs/architecture/events.md`; `docs/architecture/servers.md` |

---

## 8. Embedded browser

| ID | Feature | What OpenBot does | Evidence |
|---|---|---|---|
| OB-140 | Persistent embedded browser | Agents open, inspect, and control a persistent browser with managed tabs and durable tab state. | `README.md`; `docs/architecture/browser.md` |
| OB-141 | Browser tools | Typed provider schemas for navigate, inspect, click, type, key, scroll, back/forward, text, screenshot, list/close tabs; fill fields. | `docs/architecture/browser.md` (Browser tool execution) |
| OB-142 | Browser profiles | Shared or named profiles with colors, per-agent selection, clearing/deleting profiles, tab close on change. | `docs/architecture/agents.md` (Browser profile); `docs/architecture/browser.md` (Browser sessions) |
| OB-143 | Tab lifecycle | Popups adopted into managed tabs, opener relationships, independent `noopener` tabs, restore rules. | `docs/architecture/browser.md` (Tab lifetime) |
| OB-144 | Secure browser authentication | Secure input card, password/OTP/CAPTCHA/passkey handoff, takeover, 1Password/Bitwarden fills, no secrets to agents. | `docs/architecture/browser.md` (Secure browser authentication); `docs/architecture/skills-and-plugins.md` |
| OB-145 | Browser identity and diagnostics | Removes Electron/OpenBot tokens from user agent except Google account step; identity diagnostics report. | `docs/architecture/browser.md` (Browser tool execution) |
| OB-146 | Downloads and uploads | Browser downloads under `~/OpenBot/Downloads`; upload staging with parser and local file checks. | `README.md` (Local data); `docs/architecture/browser.md` |
| OB-147 | Remote browser live view | Web and mobile members stream a host tab, take/release control from the agent, stop page loads, and relay a host-side sign-in. | `docs/architecture/browser.md` (Tab lifetime); `docs/architecture/servers.md` (Browser control and page state) |

---

## 9. Computer use and remote desktop

| ID | Feature | What OpenBot does | Evidence |
|---|---|---|---|
| OB-160 | Cross-platform Computer Use | `cua-driver` daemon and per-provider MCP proxy on macOS, Windows, and Linux; screen capture, accessibility, input. | `README.md`; `docs/architecture/computer-use.md` |
| OB-161 | Driver lifecycle | Pinned binary, in-process daemon, MCP config for every provider, tool fingerprints, restart/teardown rules, no vendor telemetry. | `docs/architecture/computer-use.md` |
| OB-162 | Agent cursor and display | Per-display cursor overlays, agent display on servers (Xvfb), screenshots via driver. | `docs/architecture/computer-use.md` (Agent display on a server) |
| OB-163 | Remote desktop | Sunshine/Moonlight streaming, permission checks, local test sessions, clipboard transfer, X11-only Linux support. | `docs/architecture/computer-use.md` (Remote desktop permission checks) |

---

## 10. Skills, MCP, plugins, connectors

| ID | Feature | What OpenBot does | Evidence |
|---|---|---|---|
| OB-180 | Agent Skills folders | Standard `<name>/SKILL.md`; provider-specific folders (`.agents`, `.claude`, `.opencode`, `.gemini`, `.cursor`, `.cline`); hash lock and disabled folder. | `docs/architecture/skills-and-plugins.md` (Skill folders) |
| OB-181 | Local skill library | Immutable revisions in `local-skills/<uuid>/<revision>/bundle.zip`; create/read/revise/install/list tools; modified files protected. | `docs/architecture/skills-and-plugins.md` (Local skill library); `README.md` (Local skills) |
| OB-182 | Marketplace | Catalog of skills and agents; browse/install/update/disable/uninstall; launch catalog and publishing flow. | `README.md` (Marketplace launch catalog); `docs/plugin-distribution.md` |
| OB-183 | Plugin bundles | A plugin is an MCP app + skills + listing text + share page; install saves host-global MCP server and pinned skills. | `docs/architecture/skills-and-plugins.md` (Plugin distribution); `docs/plugin-distribution.md` |
| OB-184 | MCP server management | Host-global MCP servers, tool discovery, OAuth sign-in, secret masking, enable/disable, inspect/test, approval before save. | `docs/architecture/agents.md` (Agent communication policy, MCP tools); `docs/architecture/integrations.md` |
| OB-185 | Built-in connectors | 1Password, Bitwarden, GitHub App/device flow, MCP proxy, bot tokens, `gh`/`git` credential helpers. | `docs/architecture/skills-and-plugins.md` (skill folders); `docs/architecture/integrations.md` |
| OB-186 | API-key requests | `request_api_key`, `list_api_keys`, `remove_api_key`; secret form saved outside workspace; agent gets only name/path. | `docs/architecture/skills-and-plugins.md` |
| OB-187 | Sign-in relays | Provider/app sign-in through a relay for remote hosts; callback rules and security checklist. | `docs/architecture/integrations.md` |

---

## 11. Replies, artifacts, and rich UI

| ID | Feature | What OpenBot does | Evidence |
|---|---|---|---|
| OB-200 | Visual replies | `html_render` publishes an HTML page above the reply, sandboxed with scripts/forms but opaque origin; `html_preview` renders a hidden preview. | `docs/architecture/agents.md` (Prompt-driven agent profiles) |
| OB-201 | MCP Apps protocol | Frame script exposes `window.openbotPage` over MCP Apps methods (`ui/message`, `ui/update-model-context`, `ui/request-display-mode`). | `docs/architecture/agents.md` |
| OB-202 | Interactive prompts / blocks | `ask_user`, `ask_ui`, `acknowledge_request` plan cards, multi-select prompts, secret forms, `ui-blocks-v1`. | `docs/architecture/agents.md`; `docs/architecture/servers.md` (UI blocks) |
| OB-203 | Attachments | Images, PDFs, MP3, MOV, ZIP; 100 MB file / 250 MB message / 10 files; managed transfers, hashes, manifests, previews. | `README.md` (Chat attachments); `docs/architecture/structure.md` |
| OB-204 | File previews | HTML, source, images, PDF, media, ZIP open in the app or file manager; sandboxed preview pages. | `docs/architecture/agents.md`; `docs/architecture/browser.md` |

---

## 12. Remote access, Team API, messaging

| ID | Feature | What OpenBot does | Evidence |
|---|---|---|---|
| OB-220 | Team API | Typed, versioned host API over WebRTC/HTTP with capability negotiation and frozen released adapters. | `docs/architecture/team-api.md`; `packages/contracts/src/team-protocol` |
| OB-221 | Remote host | Join a server, remote agents/chats/files/browser/desktop, owner/admin roles, invitations, sessions. | `docs/architecture/servers.md`; `docs/architecture/browser.md` |
| OB-222 | Remote capabilities | Incremental optional capabilities: tasks, channels, storage, imports, flows, usage, hidden agents, side questions, etc. | `docs/architecture/servers.md` (Admin capabilities, capabilities) |
| OB-223 | External messaging | Slack, Discord, Telegram connectors with orchestrator agents, thread mapping, approvals, stop/cancel, workspace memories, limits. | `docs/messaging.md`; `docs/architecture/channels-and-messaging.md` (Messaging connections) |
| OB-224 | Mobile remote | Pairing, account, server drawer, chat, tasks, channels, browser, marketplace, push notifications, Live Activities, app lock. | `apps/mobile/src/features/*`; `apps/mobile/README.md` |
| OB-225 | Web client | Browser workspace with chat, sidebar, channels, marketplace, provider settings, usage, admin surfaces. | `docs/architecture/browser.md` (Browser client); `docs/web-client.md` |
| OB-226 | Per-agent member roles | Custom roles grant `none`/`view`/`chat`/`manage` per agent, controlling member visibility and writes. | `docs/architecture/servers.md` (Roles) |

---

## 13. Security, privacy, and operations

| ID | Feature | What OpenBot does | Evidence |
|---|---|---|---|
| OB-240 | Electron trust boundary | Sandboxing, context isolation, navigation policy, IPC sender validation, preload decoding, CSP. | `AGENTS.md` (Non-negotiable); `docs/architecture/structure.md`; `src/main/ipc` |
| OB-241 | Full-access agent model | Agents run with `danger-full-access` and no per-action approvals after first-launch consent; explicit product warning. | `README.md` (Warning); `AGENTS.md` |
| OB-242 | Secret redaction | Redacts secrets on every log, export, send, diagnostics, and analytics path. | `AGENTS.md` (Non-negotiable); `packages/logging` |
| OB-243 | Approval automation | Per-agent access levels (Workspace only / Ask first / Full access); pending questions, approvals, browser takeovers; automation file. | `docs/architecture/structure.md` (State ownership) |
| OB-244 | Resource and process monitoring | CPU/RAM/event-loop/database sampling, provider process trees, crash spans, bounded local summary. | `docs/architecture/analytics.md` (Resource sampling) |
| OB-245 | Diagnostics export | Local, privacy-safe diagnostics from the account menu. | `README.md` (What works); `docs/TROUBLESHOOTING.md` |
| OB-246 | Sandboxing and confined agents | Process confinement for workspace-only agents, protected skill folders, workspace sandbox. | `docs/architecture/skills-and-plugins.md`; `src/backend/agent/workspace-sandbox.ts` |

---

## 14. Features that are OpenBot-specific and not direct PaliMind targets

These are real OpenBot features, but they belong to OpenBot's Electron/Cloudflare
product boundary rather than the PaliMind agent runtime. The plan records them as
deferred or rejected so the review is complete.

| ID | Feature | Decision |
|---|---|---|
| OB-01/OB-11 | Electron shell, release signing, AppImage/DMG/NSIS, auto-update | Reject as direct copies; PaliMind uses Tauri and its own release pipeline. |
| OB-05/OB-06 | Cloudflare accounts, teams, D1, Stripe billing | Defer; PaliMind is local-first with no account requirement. |
| OB-07 | Hosted sites, server storage plans | Defer; not agent-runtime work. |
| OB-08 | Public status page and team status webhooks | Reject; OpenBot project operations, not a product feature. |
| OB-13 | Multi-tenant macOS hosting | Reject/defer; PaliMind is a single-user desktop app. |
| OB-226 | Per-agent member roles | Defer with Phase 9; requires membership, which PaliMind does not have today. |
| OB-09 (website/mobile analytics) | OpenPanel marketing analytics | Reject; PaliMind sends no telemetry. Keep only local agent usage analytics (OB-09 agent part). |
| OB-10 | Five-language i18n | Defer; useful later, not part of agent parity. |
| OB-163 | Sunshine/Moonlight remote desktop | Defer; PaliMind already has local desktop control and no remote-desktop product. |
| OB-240 | Electron sandbox/preload specifics | Adapt the principles to PaliMind's Tauri/Python boundary; do not copy Electron code. |
| OB-241 | `danger-full-access` default | Reject; PaliMind keeps its approval gate and sandbox. |

---

## 15. Evidence index

Primary OpenBot files used for this inventory:

- `~/openbot/README.md`
- `~/openbot/docs/ARCHITECTURE.md`
- `~/openbot/docs/architecture/agents.md`
- `~/openbot/docs/architecture/providers.md`
- `~/openbot/docs/architecture/browser.md`
- `~/openbot/docs/architecture/computer-use.md`
- `~/openbot/docs/architecture/channels-and-messaging.md`
- `~/openbot/docs/architecture/skills-and-plugins.md`
- `~/openbot/docs/architecture/integrations.md`
- `~/openbot/docs/architecture/events.md`
- `~/openbot/docs/architecture/servers.md`
- `~/openbot/docs/architecture/analytics.md`
- `~/openbot/docs/architecture/structure.md`
- `~/openbot/docs/automation.md`
- `~/openbot/docs/messaging.md`
- `~/openbot/docs/webhooks.md`
- `~/openbot/docs/status-webhooks.md`
- `~/openbot/docs/plugin-distribution.md`
- `~/openbot/docs/web-client.md`
- `~/openbot/src/backend/**`
- `~/openbot/src/main/**`
- `~/openbot/packages/contracts/src/team-protocol/**`
- `~/openbot/apps/mobile/src/features/**`

PaliMind files used for the baseline in the plan (relative to the PaliMind
repository, not `~/openbot`):

- `packages/backend/palimind/agents/**`
- `packages/backend/palimind/jobs/**`
- `packages/backend/palimind/workflows/**`
- `packages/backend/palimind/events/**`
- `packages/backend/palimind/opencode/**`
- `packages/backend/palimind/llm/mixture_of_expert/**`
- `packages/backend/palimind/api_server.py`
- `packages/backend/palimind/api_routers/routers/**`
- `packages/backend/palimind/settings.py`
- `packages/backend/tests/**`
- `packages/frontend/src/features/agents/**`
