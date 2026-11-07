# Agent parity notes — closing the gap with hosted agent bots

This document tracks how PalIAgents compares with hosted agent products such as
Grok, ChatGPT agents and Perplexity, and records the concrete work that moves
the local agent runtime closer to them. It is deliberately capability-based:
every row points at code or a test that can be run locally. For an explicit
Grok-by-Grok status table, including honest remaining gaps, see
[`grok-comparison.md`](grok-comparison.md).

## Capability matrix

| Capability | Hosted bot baseline | PaliMind before | PaliMind now |
|---|---|---|---|
| Streaming answer | Token stream | Yes (`agent:token`, `useChatStream`) | Yes |
| Visible reasoning | Collapsible thinking | Yes (`agent:thought`, activity panel) | Yes |
| Tool calling | Native function calls | Yes, typed JSON Schema + parallel read-only calls | Yes |
| Live task plan / checklist | Todo list that updates as work proceeds | Plan only for plan-review runs; no mid-run checklist | **New:** `todo_write` tool + `agent:todo` event + live checklist UI |
| Context management | Automatic summarisation of long tool output | Head-truncate at 8k chars | **Improved:** head + tail compaction with an explicit elision marker |
| Web + social search | Web, news, X | Web, X, arXiv, RSS, GitHub, HN | Same (verified by `test_web_search_upgrades.py`) |
| Citations | Inline numbered sources | Source ledger + citation map | Same |
| Memory | Cross-chat memory | Hybrid memory with recall/forget tools | Same |
| Planning | Plan then act | `review` / `auto` planning modes | Same |
| Self-critique | Verify and retry | Structured checklists + bounded retry | Same |
| Computer use | Browser/desktop control | Linux AT-SPI + CDP, approval-gated | Same |
| Follow-up / steering | Mid-run steering | `steer`, `pause`, `resume`, `cancel` | Same |
| Follow-up suggestions | 2–4 next-step chips after an answer | None | **New:** `agent:suggestions` + light-model generation with a deterministic fallback; rendered in chat and the home live card, persisted on the run record and shown in run history |
| Budget exhaustion | Retry/fallback to a stronger model | Forced wrap-up on the same model | **New:** automatic escalation through an ordered model list with a cost ceiling (`PALIMIND_AGENT_ESCALATION_MODELS`, `PALIMIND_AGENT_ESCALATION_MAX_USD`), with an `agent:escalation` event |
| Usage transparency | Token counts and cost | Only in run history after the fact | **New:** live `agent:usage` events, cumulative tokens, per-stage breakdown (classifier, planning, agent, verification, follow-ups) and a configurable cost estimate |
| Task planning | Plan grounded in available material | Generic plan text | **New:** retrieval-aware checklist seeding from matching workspace files, emitted before the first turn |

## What changed in this pass

### 1. A real run checklist (`todo_write`)

Local models drift on long tasks. The new `todo_write` tool lets an agent keep a
short, authoritative checklist in the run context:

```json
{
  "items": [
    { "label": "Find primary sources", "status": "completed" },
    { "label": "Read the top three", "status": "in_progress" },
    { "label": "Write the brief", "status": "pending" }
  ]
}
```

- Backend: `palimind/llm/mixture_of_expert/tools.py` (`todo_write`,
  `get_todo_items`, `clear_todo`), registered as a tier-1 tool.
- Agent loop: emits `agent:todo` after every checklist update, and the system
  prompt tells the model to use it for work of three or more steps.
- UI: `RunRecorder` maps `agent:todo` into the normalized plan model and
  `ActivityPanel` renders a `Plan · n/m done` checklist above the tool timeline.
- Tests: `test_pass2_agent_loop.py` (normalisation, JSON-string input, event
  emission), `activityRecorder.test.mjs`, `renderSmoke.tsx`.

### 2. Smarter long tool results

`_compact_tool_result` keeps 65% of the head and the tail of an oversized tool
result, with an explicit “characters elided” marker. The tail usually holds the
summary, totals or error that blind truncation used to discard.

### 3. Live run peek on the mission-control home

“Ask” on the agents home used to start a run and show only a toast, so the
answer was invisible until the user opened the agent. The home now shows a live
run card while the request is in flight: streamed answer text, the current
step/thought, tool chips, the todo checklist with progress, Stop, and an
“Open” action once settled. This makes the home a real mission-control surface
instead of a launcher.

Code: `AgentsHome.tsx` (`LiveRunCard`) and `AgentsHome.css`.

### 4. Follow-up suggestions

After a successful answer the runtime asks the light model for 2–4 next
actions, then emits `agent:suggestions`. `suggestions.py` always falls back to
tool-aware deterministic suggestions, so an offline or slow model cannot delay
or block delivery. The chat answer and the home live card render the chips;
clicking one prefills the composer.

Code: `agents/suggestions.py`, `runtime.py`, `StreamingMessage.tsx`
(`LiveRunFooter`), `AgentsHome.tsx`.

### 5. Automatic model escalation

When the step budget runs out without a `FINAL_ANSWER`, the run emits
`agent:escalation` and performs the forced synthesis with a stronger model:

- `PALIMIND_AGENT_ESCALATION_MODEL` when configured;
- otherwise the knowledge base's chat model if the agent uses a different one.

If no stronger model exists the run still completes with the existing wrap-up
path, so this is a pure improvement, never a new failure mode.

Code: `run_agent(..., escalation_model=, escalation_url=)`,
`agents/runtime.py`, settings in `palimind/settings.py`.

### 6. Live token and cost visibility

Every model call in the agent loop emits cumulative `agent:usage`; the runtime
adds `estimated_cost_usd` from `PALIMIND_COST_INPUT_PER_MTOK` /
`PALIMIND_COST_OUTPUT_PER_MTOK` (0 for local models). `agent:completed` carries
the final usage and suggestions. The chat answer and home live card show
`prompt in · completion out · cost`, with an “Escalated to …” chip when
applicable.

### 7. Retrieval-aware checklist seeding

Before the first model turn, `run_with_definition` scores workspace paths
against the task and seeds a 3-item checklist (review the matching material,
complete the work, verify/cite). The seed is emitted as `agent:todo`
immediately, injected as `[CHECKLIST]`, and remains editable by the model
through `todo_write`. This means the UI shows a real plan even before the first
token, and the plan references files that actually exist.

Code: `_suggest_checklist`, `_checklist_prompt_block` in
`palimind/agents/runtime.py`.

### 8. Persisted follow-ups and per-stage usage

- `record_run` now stores `suggestions` and `usage_stages` alongside the answer.
- The runs view shows follow-up chips and a token chip per stage
  (`classifier`, `planning`, `agent`, `verification`, `followups`).
- `agent:completed` carries the same breakdown for clients that want it live.

### 9. Escalation policy tuning

Escalation is now configurable rather than a single hard-coded fallback:

```bash
PALIMIND_AGENT_ESCALATION_MODELS="qwen3.5:9b,deepseek-r1:7b"
PALIMIND_AGENT_ESCALATION_MODEL="qwen3.5:9b"   # legacy single override
PALIMIND_AGENT_ESCALATION_MAX_USD=0.05          # 0 = no ceiling
```

The runtime walks the ordered list, skips models that are not installed or are
the current model, and falls back to the knowledge base chat model. The cost
ceiling is checked against the run's accumulated usage before escalating; when
it is exceeded the run stays on the current model and the `agent:escalation`
event records `skipped: true` plus the reason.

### 10. Capability-aware model routing

`palimind/agents/model_routing.py` classifies the task (tools, vision, code,
reasoning depth, context) and picks a model:

```bash
PALIMIND_AGENT_MODEL_ROUTING=auto        # off | local | auto | frontier
PALIMIND_FRONTIER_MODELS=grok-4.7,...
PALIMIND_FRONTIER_MIN_COMPLEXITY=high
```

- hard needs (tools/vision/code) are matched from `model_capabilities`;
- a complex task on a small local model can use a reasoning-capable local
  model, or the configured frontier fallback;
- the route is emitted as `agent:model_route`, stored on the run record, and
  shown in run history with the model/provider.

Live proof (`benchmarks/routing-live-2026-11-07.json`): a high-complexity task
on `qwen3.5:4b` routed to `grok-4.7`; both routes answered correctly
(`SAVED=3192`), the routed run was 41% faster (26.8s vs 45.1s). Run it with
`make routing-probe`.

### 11. Head-to-head benchmark harness

The benchmark now supports a second live run against a hosted baseline:

```bash
make agent-benchmark-vs-grok AGENT_BENCH_MODEL=qwen3.5:9b
```

It runs the identical scenarios/tools/fixtures against Grok-4.7 through a
direct OpenAI-compatible client with native `tool_calls` and `role=tool`
messages, then writes a combined report with per-scenario winners. The latest
native run is a **100% vs 100% tie** (local 9B vs Grok-4.7); see
`docs/grok-comparison.md`. This is a workflow benchmark, not a
frontier-reasoning benchmark.

### 12. Optional X API and thin web/mobile client

- `x_search` prefers X API v2 recent search when `PALIMIND_X_BEARER_TOKEN` is
  configured; otherwise it keeps the dependency-free public-index fallback.
- `GET /client` serves a small mobile-friendly chat page over the existing
  `/v1/models` and `/v1/chat/completions` endpoints, using the per-install
  bearer token. No second frontend build or hosted account is required.

### 13. UI contract hygiene

The home “Computer use” callout was using teal/violet gradients, which the MONO
design contract forbids for chrome. It now uses neutral surface tokens, so
`node scripts/check-mono.mjs --strict` is clean.

## Repeatable capability benchmark

`scripts/agent_capability_benchmark.py` runs five scenarios through the real
agent loop and writes a JSON report:

| Scenario | What it proves |
|---|---|
| `research_citations` | multi-step search/fetch, source ledger, inline citations, checklist completion, tool accuracy |
| `coding_fix` | read → edit → verify, checklist completion, no unverified edit |
| `tool_recovery` | recovers from a failed tool call and grounds the answer in the file it finally read |
| `checklist_completion` | the “finish open items before FINAL_ANSWER” guard works |
| `ui_followup_flow` | checklist/tool/usage/escalation/suggestion state survives the UI recorder and reducer |

Run it locally:

```bash
make agent-benchmark                  # deterministic, no model required
make agent-benchmark-live             # qwen3.5:4b by default
make agent-benchmark-live AGENT_BENCH_MODEL=qwen3.5:9b
```

Reports live in `benchmarks/agent-capability-*.json` (see
`benchmarks/README.md`). The benchmark also runs inside pytest
(`test_agent_capability_benchmark.py`), so the deterministic path is part of the
normal CI gate.

### Baseline results

| Run | Model | Result | Time |
|---|---|---|---|
| `agent-capability-live-9b-2026-11-06.json` | `qwen3.5:9b` | **5/5, 100%** | 621.6s |
| `agent-capability-live-2026-11-06.json` | `qwen3.5:4b` | **5/5, 100%** | 382.9s |
| `agent-capability-scripted-2026-11-06.json` | scripted | **5/5, 100%** | 0.2s |
| `agent-capability-vs-grok-native-9b-2026-11-07.json` | `qwen3.5:9b` vs `grok-4.7`, native tool calls | **100% vs 100%** (tie) | 995s + 53s |
| `agent-capability-vs-grok-2026-11-06.json` | `qwen3.5:4b` vs `grok-4.7` (earlier proxy run) | **80% vs 80%** (tie) | 321s + 151s |

All live runs are local and network-free: search/fetch use a fixture corpus, so
the score measures orchestration quality rather than internet availability.

## Agent-loop fixes driven by the benchmark failures

The first live run scored 2/5. The benchmark exposed six genuine runtime gaps,
now fixed:

1. **Plain answers were not accepted.** Native-tool models often answer without
   the text-protocol `FINAL_ANSWER:` marker, so the loop kept “continue working”
   until the step budget and then synthesised a weaker answer. A plain
   non-narration response is now accepted as the final answer.
2. **Research loops burned the budget.** Five consecutive search/fetch calls
   with no synthesis now trigger an early synthesis pass. Exact-argument loops
   still use the original detector.
3. **Checklist updates could masquerade as work.** The prompt now says
   checklist updates are bookkeeping, not progress, and requires a real tool
   between list updates.
4. **Edits were not verified.** After a file mutation the loop asks for a
   read/test before accepting the final answer, and the final-answer guard
   enforces it once.
5. **Synthetic tool lines became answers.** Small models echoed
   `[tool call: …]` / `Using …` lines back as if they were final answers. The
   loop rejects those, retries the exhaustion synthesis as plain prose, and
   falls back to the best substantive assistant message only as a last resort.
6. **Checklist bookkeeping could starve the real task.** Added a per-run
   update cap (only updates that reduce open items are accepted after the cap),
   a “no work tool used yet” nudge, a closeout step near the step limit, and a
   runtime closeout after a delivered answer so a finished run never shows
   stale open items.

## Next candidates

1. **Retrieval-aware checklist items** so the plan is seeded from workspace
   contents instead of the task text alone.
2. **Cache follow-ups in the run record and show them in history**, so a
   reopened conversation keeps its chips.
3. **Per-stage usage breakdown** (planner, tools, verification, follow-ups)
   instead of one cumulative counter.
4. **Escalation policy tuning** (cost ceiling, model allowlist) rather than a
   single fallback model.
