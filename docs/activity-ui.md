# Activity UI contract

The run surface is one normalized engine rendered per mode. Everything the UI
draws comes from `ActivityState` (`src/components/activity/model.ts`). Nothing
in the UI reads raw SSE payloads.

## Live path

1. `src/stream/useChatStream.ts` creates a `RunRecorder` per send.
2. `RunRecorder` (`src/components/activity/recorder.ts`) is the only file that
   knows backend event names. It translates them into `ActivityEvent`s.
3. `ActivityStore` (`src/components/activity/store.ts`) batches events per
   animation frame, applies the pure reducer, and notifies per-step listeners.
4. `RunSurface` chooses a mode renderer from `ActivityState.mode`.

## Backend events already used

| SSE type | Activity effect |
| --- | --- |
| `thinking` | `reasoning.delta` |
| `reasoning` | phase inference plus reasoning/status line |
| `progress` | phase inference |
| `agent_progress` | `expert.start` / `expert.end`, analyzing phase |
| `agent_thinking` | `expert.delta` |
| `agent:thought` | `reasoning.delta` |
| `agent:tool_call` | `tool.start` (normalized tool name, args) |
| `agent:tool_result` | `tool.end`, search results and passages feed sources |
| `agent:waiting_for_human` | `tool.start` with `awaitingApproval` + approval metadata |
| `agent:plan` / `research_plan` | `plan.set` |
| `agent:todo` | `plan.set` with `done` / `running` / `pending` statuses (live agent checklist) |
| `sources` | `source.add` for each file path |
| `citations` | `retrieval.result` passages |
| `citation_map` | sources plus document passages |
| `agent:token` / `token` / `agent:completed` / `answer_final` | answer start |
| `agent:usage` | live cumulative prompt/completion tokens and estimated cost |
| `agent:escalation` | shows the “Escalated to …” chip |
| `agent:suggestions` | follow-up chips after the answer settles |
| `error` / `done` | `run.error` / `run.end` |

## Signals the backend should add for full fidelity

The UI already degrades gracefully, but these data parts make the remaining
surfaces exact rather than inferred:

- `run.start { run_id, mode }` and `run.end { status }` so a run can be
  identified without client-generated ids.
- `tool.start { id, name, args, parent_id?, group_key?, started_at }` and
  `tool.end { id, status, output?, error? }`. Today tool results are attached
  to the most recent call because results carry no id. Ids make parallel and
  nested (delegate) work exact.
- `tool.progress { id, text }` for streamed terminal output. The UI stores
  streamed text in append-only buffers outside React state; cap is 2000 lines
  or 256 KB with head and tail retained.
- `approval.requested { id, tool, args, agent_id, run_id }` and
  `approval.resolved { id, decision }`. The current approval card is inline and
  restores from the persisted state, but resolving it still calls
  `POST /agents/{agent_id}/approve`.
- `phase { phase }`, `plan.step { id, status }`, `expert.start/delta/end`, and
  `source.add { item }`. These are inferred from text today; explicit events
  remove the heuristics.
- Sub-agent tool calls need `parent_id`; browser tools need `group_key` so a
  session merges even when calls are not strictly consecutive.
- `tool.start` should include `started_at` and `tool.end` `ended_at` for exact
  durations and the Gantt view.

## Adding a tool

Add one row to `TOOL_REGISTRY` in `src/components/activity/toolRegistry.ts`:
icon name, running label (present participle), done label (past tense), family,
preview extractor, and `approval: true` when it mutates. Unknown tools already
fall back to the wrench family with a humanized name. Add the icon to
`src/components/activity/icons/index.tsx` (or `icons/brands.tsx` for a brand
mark) and run the registry test, which asserts all 48 entries are complete.

## Adding a body family

Create `bodies/YourBody.tsx` taking `{ step }` (and `store` only if it needs
buffers). Export it from `bodies/ToolBody.tsx` through `React.lazy`, add the
family to `ToolFamily` in `model.ts`, and map the tool family in the registry.
Use the shared primitives: `CodeView`, `Terminal`, `DiffView`, `DataTable`,
`CopyButton`, `Highlight`. Cap rendered output and offer "Show all".

## Adding a mode

Add a renderer under `modes/` with the `ModeProps` signature, add the id to
`RunMode`, map it in `modeFromActivityMode` (`adaptRun.ts`), and dispatch it in
`shell/RunSurface.tsx`. Keep the final answer as the children below the panel.

## Normalized events (spec §13)

The target vocabulary. The recorder already emits every event below into
`ActivityStore`; today's SSE is translated to these event shapes by
`recorder.ts` (adapter fallback), so the UI works unchanged until the backend
ships them natively.

| Event | Payload | Adapter fallback (today) |
| --- | --- | --- |
| `run.start` | `{ run_id, mode, title? }` | client-generated `runId`, title from send metadata |
| `run.end` | `{ status: done \| stopped \| error, error? }` | `agent:completed` / `answer_final` / `error` |
| `tool.start` | `{ id, name, args, parent_id?, group_key?, started_at }` | `agent:tool_call` / `agent:waiting_for_human` |
| `tool.progress` | `{ id, text }` | streamed tool output deltas (`tool.delta`) into append-only buffers |
| `tool.end` | `{ id, status, output?, error?, ended_at }` | `agent:tool_result` |
| `tool.approval` | `{ id, status: awaiting_approval \| running \| denied \| cancelled }` | `agent:waiting_for_human` (start) and `resolveApproval` (client decision) |
| `plan.set` / `plan.step` | `{ steps[] }` / `{ id, status }` | `agent:plan` / `research_plan` / agent_progress |
| `phase` | `{ phase: routing \| searching \| reading \| analyzing \| synthesizing \| writing }` | inferred from `progress`/tool names |
| `expert.start` / `expert.delta` / `expert.end` | MoE expert lifecycle | `agent_progress` / `agent_thinking` |
| `source.add` | `{ item: ResultItem }` | `sources`, `citation_map` |
| `retrieval.result` | `{ passages: Passage[] }` | `citations`, `citation_map` |
| `text.delta` | answer tokens | `agent:token` / `token` |

### Derived fields (no UI scraping of raw payloads)

- **Duration**: `tool.end.at - tool.start.startedAt` → `step.durationMs`;
  `run.end.at - run.start.startedAt` → run duration. Neither the reducer nor
  the UI reads timestamps from raw SSE.
- **`sources[]`**: search outputs are normalized by `normalizeResults`
  (`toolOutput.ts`) at ingest (`recorder.ingestOutput`) and deduped by id in
  the reducer. Citation payloads flow through `resultsFromSources`.
- **`passages[]`**: `citations` / `citation_map` / `retrieval.result` are
  normalized by `normalizePassages` and deduped by id in the reducer.

### Approval semantics

- `agent:waiting_for_human` opens an inline receipt (`PermissionGrant`) with
  the exact payload and a plain-English action line. It never auto-approves.
- `POST /agents/{agent_id}/approve` remains the resolution transport; the
  store mirrors the decision as `tool.approval` so the receipt settles.
- A run that ends while a request is pending is persisted as `cancelled`, so a
  restored receipt never pulses forever. Restored receipts (`ActivityStore
  .restored`) render with a "Requested earlier" note and no attention pulse.

## Presentation (v2)

- **Caption row** (`shell/ActivityPanel.tsx`): one hairline row —
  `[spine node] [avatar/status] [caption] [tool icons] [Sources · N] [chevron]`.
  The caption string comes from `caption.ts` (`captionFor(state)`), the single
  derivation used by the panel, the composer line and the aria-live region.
  Priority: pending approval → running tool → phase → reasoning → settled →
  failed. Settings (Auto / Always expanded / Always collapsed) and the
  rail/timeline toggle live behind the overflow button; `T` toggles the same
  timeline on the live panel (never while typing).
- **Phase spine** (`shell/PhaseSpine.tsx`): three equal-weight 2px segments
  (Gather, Analyze, Write) filled by `phase` events; hidden under reduced
  motion. No percentages.
- **Reasoning trace** (`shell/ReasoningBlock.tsx`): live three-line tail from
  the `reasoning` buffer with a top fade and a shared timer; settled form is a
  single «Thought for Ns» line that re-opens the full trace. Reasoning text
  never enters React state.
- **Intent clusters** (`grouping.ts`): consecutive research/writing/running
  steps fold into one disclosure; completed parallel calls keep the
  "Ran N tools" row; browser sessions stay one card; delegates recurse through
  `bodies/SubagentBody.tsx` (depth cap 3).
- **Approval receipt** (`shell/PermissionGrant.tsx`): dashed warning edge,
  plain-English action, exact payload with secret masking, destructive
  warning, `Enter` allow once · `A` allow for this run · `Esc` deny. Restored
  receipts render "Requested earlier" with no attention pulse.
- **Playground**: dev-only `/#/activity` with every scenario, theme and
  reduced-motion toggles, replay speed, and a restored-pending-approval case.
