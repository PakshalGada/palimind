# PaliMind vs Grok — capability-by-capability comparison

Last updated: 2026-11-06. This is deliberately blunt: it separates features we
have reached parity on from the places where a hosted frontier model is still
ahead. The goal is not to claim Grok parity everywhere; it is to make every gap
explicit and measurable.

Legend: **Comparable** = same capability class, **Stronger** = PaliMind does
more or does it locally, **Partial** = works but with a narrower source or
modality, **Gap** = Grok is materially ahead.

| Capability | Grok bot | PaliMind today | Status |
|---|---|---|---|
| Base model quality | Frontier Grok models | Local Qwen/DeepSeek/Gemma via Ollama, capability-aware routing, optional OpenCode frontier fallback | **Gap** — local 4B–9B models do not match frontier reasoning; the router can move hard tasks to a configured frontier model |
| Web search + citations | Native, real-time web | SearXNG/DuckDuckGo, page fetch, source ledger, inline citations | **Comparable** |
| X/Twitter signal | Native X firehose | `x_search` uses X API v2 recent search when `PALIMIND_X_BEARER_TOKEN` is set; otherwise the public web index. Sentiment/trend extraction either way. | **Partial** — optional X API supported; no firehose/default credentials |
| Multi-step research | DeepSearch-style planning | Deep Research mode, parallel agents, plan approval, cited report | **Comparable** for the workflow; model depth remains a gap |
| Agent tool use | Native tools and connectors | 50+ typed tools, parallel reads, approval gates, tool routing, MCP | **Comparable**; verified by the capability benchmark |
| Coding agent | Code generation and execution | Read/edit/apply-patch/git/office/data tools, verification guard | **Comparable** for local repos |
| Desktop / computer use | Browser-centric | Linux AT-SPI2 + CDP, approval per mutating action, audit log | **Stronger** on Linux desktop |
| Image understanding | Native multimodal | Local vision model routing via Ollama | **Partial** — quality depends on the local vision model |
| Image generation / editing | Hosted image model | Optional ComfyUI / stable-diffusion.cpp | **Partial** — needs a local backend |
| Voice conversation | Low-latency hosted voice | Local Whisper + Kokoro live voice loop, barge-in | **Partial** — functional but higher latency |
| Memory | Conversation memory | Hybrid vector + lexical memory, recall/forget tools, consolidation | **Comparable** |
| Scheduled / background work | Tasks and reminders | Durable jobs, cron/interval/webhook routines, queue, retries | **Stronger** for local automation |
| Long-running transparency | Streaming reasoning and search | Live checklist, tool timeline, token/cost meter, escalation events | **Stronger** — more local observability |
| Follow-ups / steering | Suggested prompts, stop/regenerate | Follow-up chips, mid-run steer/pause/resume/stop | **Comparable** |
| Privacy / offline | Cloud-first | Local-first, no telemetry, nothing leaves the machine by default | **Stronger** |
| Mobile / web access | Hosted apps | Desktop app; local OpenAI-compatible API; thin mobile-friendly client at `/client` | **Partial** — usable on a phone over the LAN, but no native app or hosted sync |
| Ecosystem / connectors | Large hosted connector catalog | Local MCP + Gmail/Drive/Slack/GitHub/calendar packs | **Partial** |
| Independent evaluation | Public benchmarks and hosted evals | Self-defined 5-scenario capability benchmark; head-to-head harness vs `grok-4.7` with native OpenAI tool calls | **Partial** — a real head-to-head exists, but the task set is still self-defined |

## What the benchmark proves

`scripts/agent_capability_benchmark.py` measures the workflow capabilities, not
raw model intelligence:

- multi-step research with sources and citations,
- coding read → edit → verify,
- recovery from a failed tool call,
- checklist completion with the finish-before-answer guard,
- UI state for checklist/usage/escalation/follow-ups.

A 5/5 score means PaliMind's *orchestration* is Grok-class for these flows. It
does **not** mean a 4B local model reasons like a frontier Grok model.

## Head-to-head with Grok-4.7

The same five scenarios can run against a hosted baseline. The harness now uses
a **direct OpenAI-compatible client** with native `tool_calls` and `role=tool`
messages, so it no longer depends on the Ollama proxy's text fallback:

```bash
make agent-benchmark-vs-grok \
  AGENT_BENCH_MODEL=qwen3.5:9b \
  AGENT_BASELINE_MODEL=grok-4.7
```

The baseline reads the OpenCode key from Settings by default; any OpenAI-
compatible endpoint/key can be supplied instead. Reports include per-scenario
winners.

Observed results (local machine, fixture search/source corpus):

| Local model | Local score | Grok-4.7 score | Winner | Report |
|---|---|---|---|---|
| `qwen3.5:9b` | **100% (5/5)** | **100% (5/5)** | **tie** | `agent-capability-vs-grok-native-9b-2026-11-07.json` |
| `qwen3.5:4b` | 80% (4/5) | 80% (4/5) | tie (earlier proxy run) | `agent-capability-vs-grok-2026-11-06.json` |

The native run is the authoritative comparison: both sides pass all five
workflow scenarios. Grok-4.7 is much faster (53s vs 995s locally), while the
local run is free, private and offline. The harness is self-defined, so this is
evidence of workflow parity, not a claim of frontier-model reasoning parity.

Both sides used native tool calls in this run. The hosted transcript uses
OpenAI `tool_calls` / `role=tool` messages; the local transcript keeps Ollama's
compact user-message format. That removes the earlier proxy caveat.

## Capability-routing live probe

A separate live probe proves that a hard task on a small local model is actually
routed to the configured frontier fallback, not just selected on paper:

```bash
make routing-probe
# or: PALIMIND_AGENT_MODEL_ROUTING=off|auto PALIMIND_FRONTIER_MODELS=grok-4.7
```

Task: a cache/CPU arithmetic problem with a deterministic answer (`SAVED=3192`).

| Route | Model | Quality | Latency |
|---|---|---|---|
| routing off | `qwen3.5:4b` (local) | pass | **45.1s** |
| routing auto | **`grok-4.7` (hosted)** | pass | **26.8s** |

The router chose `grok-4.7` because the task was `high` complexity and the
requested model was a 4B local model. The routed run was **41% faster** with the
same answer. Report: `benchmarks/routing-live-2026-11-07.json`.

A second manual run was slower on both sides (63.5s local, 29.7s routed), so the
exact speedup varies with local load; the routing decision and quality were
stable.

## Where to close the remaining gaps

1. **Model quality** — keep an OpenCode/frontier fallback for hard tasks; make
   model routing capability-aware (tools/vision/reasoning/context).
2. **X firehose** — optional X API integration is wired; the remaining work is
   filtering/rate-limit policy and an X OAuth/connect flow.
3. **Image/video generation** — first-class local backends and a model manager.
4. **Voice latency** — streaming STT/TTS and smaller local models.
5. **Mobile/web** — `/client` is a working thin client; next is installable PWA
   metadata and a QR/deep-link helper from Settings.
6. **External evaluation** — publish the benchmark tasks and extend the
   head-to-head harness beyond the self-defined set (the Grok baseline is now
   wired, but proxy/tool-call compatibility still needs hardening).
