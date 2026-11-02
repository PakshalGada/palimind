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
| `sources` | `source.add` for each file path |
| `citations` | `retrieval.result` passages |
| `citation_map` | sources plus document passages |
| `agent:token` / `token` / `agent:completed` / `answer_final` | answer start |
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
mark) and run the registry test, which asserts all 47 entries are complete.

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
