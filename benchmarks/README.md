# Benchmarks

## Agent capability benchmark

`agent-capability-*.json` is produced by
`scripts/agent_capability_benchmark.py` (also `make agent-benchmark` and
`make agent-benchmark-live`).

Scenarios:

| ID | Category | What it measures |
|---|---|---|
| `research_citations` | research | multi-step search/fetch, source ledger, citations, checklist |
| `coding_fix` | coding | read → edit → verify, checklist, unverified-edit guard |
| `tool_recovery` | tool_use | failed call recovery and grounded answer |
| `checklist_completion` | checklist | finish open items before `FINAL_ANSWER` |
| `ui_followup_flow` | ui | checklist/tool/usage/escalation/suggestion state |

Regenerate:

```bash
make agent-benchmark
make agent-benchmark-live AGENT_BENCH_MODEL=qwen3.5:9b
make agent-benchmark-vs-grok AGENT_BENCH_MODEL=qwen3.5:9b
```

`agent-capability-vs-grok*.json` is a head-to-head report: it runs the same
scenario suite against a local model and a hosted baseline (`grok-4.7` through
the direct OpenAI-compatible OpenCode Zen endpoint by default) and records
per-scenario winners.

`routing-live*.json` proves capability-aware routing on a hard deterministic
task: routing off runs the small local model; routing auto selects the
configured `grok-4.7` frontier fallback. The combined report records model,
provider, latency and quality.

Reports include per-scenario checks, tool sequence, tool accuracy, todo state,
token usage and a `score` / `meets_target` summary. The deterministic report is
also asserted by `tests/test_agent_capability_benchmark.py`.

## Desktop benchmarks

`desktop-dogfood-*.json` and `x11-validation-*.json` are produced by the
existing desktop-use gates (`make desktop-dogfood`, `make desktop-x11-check`).
`desktop-dogfood-2026-11-09.json` is the post-reliability-pass run: 20/20,
zero screenshots, 50 snapshots.
