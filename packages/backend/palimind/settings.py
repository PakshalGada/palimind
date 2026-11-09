from __future__ import annotations

"""Global application settings for agent features.

Kept intentionally small: only the knobs referenced by the agent
subsystem live here. Environment variables can override each value.
"""

import os


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if raw.isdigit():
        return int(raw)
    return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        return float(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str | None = None) -> str | None:
    raw = os.environ.get(name, "").strip()
    return raw or default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "")
    if raw.strip().lower() in ("1", "true", "yes", "on"):
        return True
    if raw.strip().lower() in ("0", "false", "no", "off"):
        return False
    return default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "")
    if raw.strip():
        return [p.strip() for p in raw.split(os.pathsep) if p.strip()]
    return default


# Master switch for the PalIAgents feature. When agents can be created,
# run manually, and invoked from chat this must be enabled.
ENABLE_PALIAGENTS: bool = _env_bool("PALIMIND_ENABLE_PALIAGENTS", True)

# ── OpenBot-parity feature flags ──────────────────────────────────────────
# Experimental layers stay behind flags until their deterministic acceptance
# tests pass. Defaults are chosen so the existing UI is unchanged.
AGENT_TASKS_ENABLE: bool = _env_bool("PALIMIND_AGENT_TASKS", True)
AGENT_MAILBOX_ENABLE: bool = _env_bool("PALIMIND_AGENT_MAILBOX", True)
AGENT_CHANNELS_ENABLE: bool = _env_bool("PALIMIND_AGENT_CHANNELS", False)
AGENT_FLOWS_ENABLE: bool = _env_bool("PALIMIND_AGENT_FLOWS", False)
AGENT_WAITS_ENABLE: bool = _env_bool("PALIMIND_AGENT_WAITS", False)
AGENT_AUTOMATION_ENABLE: bool = _env_bool("PALIMIND_AGENT_AUTOMATION", False)
AGENT_BROWSER_PROFILES_ENABLE: bool = _env_bool("PALIMIND_AGENT_BROWSER_PROFILES", False)
AGENT_USAGE_ENABLE: bool = _env_bool("PALIMIND_AGENT_USAGE", True)
AGENT_SUBAGENTS_ENABLE: bool = _env_bool("PALIMIND_AGENT_SUBAGENTS", True)
AGENT_SIDE_QUESTIONS_ENABLE: bool = _env_bool("PALIMIND_AGENT_SIDE_QUESTIONS", True)
AGENT_SHARED_DATA_ENABLE: bool = _env_bool("PALIMIND_AGENT_SHARED_DATA", False)

# Task lane limits. An agent's own task_limit may be lower but never higher.
AGENT_TASK_LIMIT_DEFAULT: int = _env_int("PALIMIND_AGENT_TASK_LIMIT", 2)
AGENT_TASK_LIMIT_MAX: int = _env_int("PALIMIND_AGENT_TASK_LIMIT_MAX", 8)
AGENT_OPEN_TASK_LIMIT: int = _env_int("PALIMIND_AGENT_OPEN_TASK_LIMIT", 50)
AGENT_QUEUE_LIMIT: int = _env_int("PALIMIND_AGENT_QUEUE_LIMIT", 100)

# Local automation listener limits.
AUTOMATION_MAX_BODY_BYTES: int = _env_int("PALIMIND_AUTOMATION_MAX_BODY_BYTES", 32 * 1024)
AUTOMATION_MAX_PAYLOAD_CHARS: int = _env_int("PALIMIND_AUTOMATION_MAX_PAYLOAD_CHARS", 4_000)
AUTOMATION_REQUESTS_PER_HOUR: int = _env_int("PALIMIND_AUTOMATION_REQUESTS_PER_HOUR", 30)
AUTOMATION_MAX_WAITS: int = _env_int("PALIMIND_AUTOMATION_MAX_WAITS", 20)

# Maximum number of entries kept in an agent's memory file. When the cap
# is hit the oldest entry is dropped.
AGENT_MEMORY_MAX_ENTRIES: int = _env_int("PALIMIND_AGENT_MEMORY_MAX_ENTRIES", 100)

# Timeout (seconds) for shell commands executed by run_shell_tool.
SHELL_EXEC_TIMEOUT: int = _env_int("PALIMIND_SHELL_EXEC_TIMEOUT", 30)

# Timeout (seconds) for Python code executed by the run_python tool. The
# value is a hard ceiling — an agent-supplied timeout is clamped to it.
PYTHON_EXEC_TIMEOUT: int = _env_int("PALIMIND_PYTHON_EXEC_TIMEOUT", 30)

# Resource limits applied to run_python subprocesses via the resource module.
PYTHON_EXEC_CPU_TIME: float = _env_float("PALIMIND_PYTHON_EXEC_CPU_TIME", 10.0)
PYTHON_EXEC_MEMORY_MB: int = _env_int("PALIMIND_PYTHON_EXEC_MEMORY_MB", 512)

# Additional absolute paths (besides the field root) that file tools may
# access. Colon/pathsep-separated list, e.g. PALIMIND_ALLOWED_PATHS=/data/a:/data/b.
ALLOWED_PATHS: list[str] = _env_list("PALIMIND_ALLOWED_PATHS", [])

# Per-tool debug trace (before/after lines) and the global tool audit log.
TOOL_DEBUG_LOG: bool = _env_bool("PALIMIND_TOOL_DEBUG_LOG", True)
TOOL_AUDIT_LOG: bool = _env_bool("PALIMIND_TOOL_AUDIT_LOG", True)

# Default wall-clock ceiling (seconds) for a single live tool call. Individual
# tools may override this via their manifest; kept generous because some
# built-ins (web search / page fetch) legitimately take a while.
TOOL_TIMEOUT_S: int = _env_int("PALIMIND_TOOL_TIMEOUT", 120)

# ── speech-to-text ────────────────────────────────────────────────────────

# faster-whisper model used by the microphone dictation (downloaded on first
# use from HuggingFace). English-only `.en` models are faster on CPU. Can be
# overridden per-user in Settings (Voice) — see palimind.audio.stt.
STT_WHISPER_MODEL: str = _env_str("PALIMIND_STT_WHISPER_MODEL", "base.en") or "base.en"

# ── backups ───────────────────────────────────────────────────────────────

# Where local backups are written (empty = ~/.palimind/backups).
BACKUP_DIR: str = _env_str("PALIMIND_BACKUP_DIR", "") or ""

# ── web search providers ─────────────────────────────────────────────────

# auto = local SearXNG when reachable, otherwise DuckDuckGo; or force one.
SEARCH_PROVIDER: str = _env_str("PALIMIND_SEARCH_PROVIDER", "auto") or "auto"
SEARXNG_URL: str = _env_str("PALIMIND_SEARXNG_URL", "http://127.0.0.1:8080") or (
    "http://127.0.0.1:8080"
)
SEARCH_TIMEOUT: float = _env_float("PALIMIND_SEARCH_TIMEOUT", 8.0)

# ── browser tools ─────────────────────────────────────────────────────────

# Domains the browser may visit. When ALLOWED is non-empty the browser is
# restricted to those (and their subdomains); BLOCKED always wins. Empty
# lists mean "allow any public host".
BROWSER_ALLOWED_DOMAINS: list[str] = _env_list("PALIMIND_BROWSER_ALLOWED_DOMAINS", [])
BROWSER_BLOCKED_DOMAINS: list[str] = _env_list("PALIMIND_BROWSER_BLOCKED_DOMAINS", [])
# Run the headless browser; set false for a visible window (debugging).
BROWSER_HEADLESS: bool = _env_bool("PALIMIND_BROWSER_HEADLESS", True)
# Navigation timeout for browser_open / click / type.
BROWSER_TIMEOUT_MS: int = _env_int("PALIMIND_BROWSER_TIMEOUT_MS", 30000)

# ── research / knowledge tools ────────────────────────────────────────────
# All research tools work without keys against public endpoints. Optional keys
# simply raise rate limits / add auth where supported.
GITHUB_TOKEN: str = _env_str("PALIMIND_GITHUB_TOKEN", "") or ""
SEMANTIC_SCHOLAR_API_KEY: str = _env_str("PALIMIND_SEMANTIC_SCHOLAR_API_KEY", "") or ""
# SEC EDGAR requires a descriptive User-Agent with a contact address.
SEC_CONTACT: str = (
    _env_str("PALIMIND_SEC_CONTACT", "palimind@example.com") or "palimind@example.com"
)

# Poll interval (seconds) for the scheduled-agent scheduler tick.
AGENT_SCHEDULER_TICK: int = _env_int("PALIMIND_AGENT_SCHEDULER_TICK", 15)

# How many run-history records to keep per agent.
AGENT_RUN_HISTORY_LIMIT: int = _env_int("PALIMIND_AGENT_RUN_HISTORY_LIMIT", 200)

# How many conversation messages to keep per agent chat log.
AGENT_CHAT_LIMIT: int = _env_int("PALIMIND_AGENT_CHAT_LIMIT", 300)

# How many relevant memory entries to inject before a run (hybrid recall).
AGENT_MEMORY_RECALL_LIMIT: int = _env_int("PALIMIND_AGENT_MEMORY_RECALL_LIMIT", 8)

# Memory 2.0: local vector recall. "hash" is dependency-free and offline;
# "ollama" uses the configured local embedding model when available.
MEMORY_EMBEDDINGS: str = _env_str("PALIMIND_MEMORY_EMBEDDINGS", "hash") or "hash"
MEMORY_SEMANTIC_WEIGHT: float = _env_float("PALIMIND_MEMORY_SEMANTIC_WEIGHT", 0.65)
MEMORY_LEXICAL_WEIGHT: float = _env_float("PALIMIND_MEMORY_LEXICAL_WEIGHT", 0.30)
MEMORY_RECENCY_WEIGHT: float = _env_float("PALIMIND_MEMORY_RECENCY_WEIGHT", 0.05)
MEMORY_CONSOLIDATE_THRESHOLD: float = _env_float("PALIMIND_MEMORY_CONSOLIDATE_THRESHOLD", 0.92)

# Extract durable facts from a successful run into agent memory (one extra
# light-model call, run in the background).
AGENT_AUTO_MEMORY_EXTRACT: bool = _env_bool("PALIMIND_AGENT_AUTO_MEMORY_EXTRACT", True)

# ── Mixture-of-Experts tuning ─────────────────────────────────────────────

# Context window (Ollama num_ctx) for MoE LLM calls. Larger windows allow
# more agent tool history but cost more tokens per call.
MOE_NUM_CTX: int = _env_int("PALIMIND_MOE_NUM_CTX", 8192)

# Approximate token budget for the *live* portion of an agent's message
# history. When the estimated size exceeds this, the oldest tool exchanges
# are compacted into a condensed "working notes" block.
MOE_CONTEXT_BUDGET_TOKENS: int = _env_int("PALIMIND_MOE_CONTEXT_BUDGET_TOKENS", 6000)

# Max parallel agents. 0 = auto (RAM- and Ollama-aware heuristic).
MOE_MAX_CONCURRENCY: int = _env_int("PALIMIND_MOE_MAX_CONCURRENCY", 0)

# Hard ceiling on tool iterations per agent (adaptive budget clamps to this).
MOE_MAX_AGENT_ITERATIONS: int = _env_int("PALIMIND_MOE_MAX_AGENT_ITERATIONS", 12)

# Maximum number of independent read-only tool calls executed concurrently
# within one agent step. Writes/approval-gated calls always run serially.
MAX_PARALLEL_TOOLS: int = _env_int("PALIMIND_MAX_PARALLEL_TOOLS", 4)

# Local chat attachments (images/PDF/text). Bytes are stored content-addressed
# under ~/.palimind/uploads; these limits keep a bad file from exhausting RAM.
UPLOAD_MAX_MB: int = _env_int("PALIMIND_UPLOAD_MAX_MB", 25)
UPLOAD_TEXT_LIMIT: int = _env_int("PALIMIND_UPLOAD_TEXT_LIMIT", 30_000)

# Tool routing: show the model only the most relevant tool schemas instead of
# every registered tool. The full allowlist is still enforced by the runtime.
TOOL_ROUTER: bool = _env_bool("PALIMIND_TOOL_ROUTER", True)
TOOL_ROUTER_TOP_K: int = _env_int("PALIMIND_TOOL_ROUTER_TOP_K", 12)

# Local MCP servers (configured in ~/.palimind/mcp.json). Each server must be
# explicitly trusted before its tools are exposed to agents.
MCP_ENABLE: bool = _env_bool("PALIMIND_MCP_ENABLE", True)

# Durable job service: worker count, poll interval and lease duration.
JOB_CONCURRENCY: int = _env_int("PALIMIND_JOB_CONCURRENCY", 2)
JOB_POLL_INTERVAL: float = _env_float("PALIMIND_JOB_POLL_INTERVAL", 2.0)
JOB_LEASE_SECONDS: float = _env_float("PALIMIND_JOB_LEASE_SECONDS", 300.0)

# Local image generation. Backends are opt-in; "off" keeps the feature hidden
# and avoids downloading/starting anything.
IMAGE_BACKEND: str = _env_str("PALIMIND_IMAGE_BACKEND", "off") or "off"
COMFYUI_URL: str = _env_str("PALIMIND_COMFYUI_URL", "http://127.0.0.1:8188") or (
    "http://127.0.0.1:8188"
)
COMFYUI_CHECKPOINT: str = _env_str("PALIMIND_COMFYUI_CHECKPOINT", "") or ""
SDCPP_BINARY: str = _env_str("PALIMIND_SDCPP_BINARY", "sd") or "sd"
SDCPP_MODEL: str = _env_str("PALIMIND_SDCPP_MODEL", "") or ""
IMAGE_TIMEOUT: float = _env_float("PALIMIND_IMAGE_TIMEOUT", 240.0)
IMAGE_MAX_SIDE: int = _env_int("PALIMIND_IMAGE_MAX_SIDE", 1024)

# Run the post-synthesis verification/critique pass (uses the light model).
MOE_VERIFY: bool = _env_bool("PALIMIND_MOE_VERIFY", True)

# Bounded retries for transient LLM failures (timeout / HTTP 5xx / 429).
LLM_RETRIES: int = _env_int("PALIMIND_LLM_RETRIES", 2)

# ── Deep Research tuning ───────────────────────────────────────────────────

# Number of research sub-topics the orchestrator creates for deep research.
DR_NUM_SUBTOPICS: int = _env_int("PALIMIND_DR_NUM_SUBTOPICS", 5)

# Max tool iterations per research agent (higher than MoE for thorough research).
DR_MAX_AGENT_ITERATIONS: int = _env_int("PALIMIND_DR_MAX_AGENT_ITERATIONS", 15)

# Context window for deep research LLM calls.
DR_NUM_CTX: int = _env_int("PALIMIND_DR_NUM_CTX", 8192)

# Max parallel research agents.
DR_MAX_CONCURRENCY: int = _env_int("PALIMIND_DR_MAX_CONCURRENCY", 3)

# Run the post-synthesis verification pass for deep research.
DR_VERIFY: bool = _env_bool("PALIMIND_DR_VERIFY", True)

# Max web search results per research agent.
DR_MAX_SEARCH_RESULTS: int = _env_int("PALIMIND_DR_MAX_SEARCH_RESULTS", 8)

# Hard cap on the search-read-synthesize steps a single research agent may take.
DR_MAX_STEPS: int = _env_int("PALIMIND_DR_MAX_STEPS", 10)

# Seconds to wait for the user to review/approve the research plan before the
# pipeline proceeds with the generated plan automatically.
DR_PLAN_REVIEW_TIMEOUT: int = _env_int("PALIMIND_DR_PLAN_REVIEW_TIMEOUT", 600)

# ── Phase 4.1: adaptive reasoning ─────────────────────────────────────────

# Master switch for dynamic reasoning-effort allocation. When disabled every
# run uses the agent's own max_iterations / context_budget unchanged.
ADAPTIVE_REASONING: bool = _env_bool("PALIMIND_ADAPTIVE_REASONING", True)

# Optional model used for the complexity classifier. Empty = light model.
REASONING_CLASSIFIER_MODEL: str = _env_str("PALIMIND_REASONING_CLASSIFIER_MODEL", "") or ""

# Auto-escalate the effort level when an agent gets stuck (repeat tool loops,
# empty answers, tool errors).
ADAPTIVE_ESCALATE_ON_STUCK: bool = _env_bool("PALIMIND_ADAPTIVE_ESCALATE_ON_STUCK", True)

# Model used for the final synthesis when an agent exhausts its step budget
# without a final answer. Empty = the knowledge base's chat model when it
# differs from the agent model (automatic escalation); same model otherwise.
AGENT_ESCALATION_MODEL: str = _env_str("PALIMIND_AGENT_ESCALATION_MODEL", "") or ""

# Ordered fallback list used before AGENT_ESCALATION_MODEL. The first model
# that is installed and differs from the agent's own model wins.
AGENT_ESCALATION_MODELS: list[str] = [
    item.strip()
    for item in (_env_str("PALIMIND_AGENT_ESCALATION_MODELS", "") or "").split(",")
    if item.strip()
]

# Optional cost ceiling (USD) for escalation. Once the run's accumulated token
# cost reaches this value the wrap-up stays on the current model instead of
# escalating. 0 disables the ceiling.
AGENT_ESCALATION_MAX_USD: float = _env_float("PALIMIND_AGENT_ESCALATION_MAX_USD", 0.0)

# Capability-aware routing: "off" | "local" | "auto" | "frontier".
# "auto" keeps local models but can move a hard task to a reasoning model or a
# configured frontier fallback. "frontier" always permits the hosted fallback.
AGENT_MODEL_ROUTING: str = _env_str("PALIMIND_AGENT_MODEL_ROUTING", "auto") or "auto"

# Comma-separated hosted/frontier model ids (OpenCode proxy or any model the
# OpenAI-compatible endpoint exposes). Empty = no hosted routing.
AGENT_FRONTIER_MODELS: list[str] = [
    item.strip()
    for item in (_env_str("PALIMIND_FRONTIER_MODELS", "") or "").split(",")
    if item.strip()
]

# Minimum complexity level that may jump to a frontier fallback.
AGENT_FRONTIER_MIN_COMPLEXITY: str = _env_str("PALIMIND_FRONTIER_MIN_COMPLEXITY", "high") or "high"

# OpenAI-compatible base URL for the hosted fallback. The default is OpenCode
# Zen, which serves models like grok-4.7 with native tool calls.
AGENT_FRONTIER_BASE_URL: str = (
    _env_str("PALIMIND_FRONTIER_BASE_URL", "https://opencode.ai/zen/go/v1")
    or "https://opencode.ai/zen/go/v1"
)

# Generate 3 short follow-up suggestions after a successful agent answer.
AGENT_FOLLOWUPS: bool = _env_bool("PALIMIND_AGENT_FOLLOWUPS", True)

# Optional per-million-token prices used to estimate a run's cost. Local
# models default to 0; set these for cloud/OpenCode proxy models.
COST_INPUT_PER_MTOK: float = _env_float("PALIMIND_COST_INPUT_PER_MTOK", 0.0)
COST_OUTPUT_PER_MTOK: float = _env_float("PALIMIND_COST_OUTPUT_PER_MTOK", 0.0)

# ── Phase 4.2: multi-agent orchestration ──────────────────────────────────

# Hard ceiling on fan-out agents spawned for one orchestrated task.
ORCHESTRATOR_MAX_AGENTS: int = _env_int("PALIMIND_ORCHESTRATOR_MAX_AGENTS", 8)

# Max parallel orchestrated agents. 0 = auto (reuse the MoE heuristic).
ORCHESTRATOR_MAX_CONCURRENCY: int = _env_int("PALIMIND_ORCHESTRATOR_MAX_CONCURRENCY", 0)

# Default number of agents an orchestrated run spawns (clamped to the max).
ORCHESTRATOR_DEFAULT_AGENTS: int = _env_int("PALIMIND_ORCHESTRATOR_DEFAULT_AGENTS", 4)

# Run the conflict-resolution pass over disagreeing agents before synthesis.
ORCHESTRATOR_CONFLICT_RESOLUTION: bool = _env_bool(
    "PALIMIND_ORCHESTRATOR_CONFLICT_RESOLUTION", True
)

# Arena mode default: run N candidates on the same task and pick the winner.
ORCHESTRATOR_ARENA: bool = _env_bool("PALIMIND_ORCHESTRATOR_ARENA", False)

# ── Phase 4.3: agent skills ───────────────────────────────────────────────

# Allow installing skills from the bundled marketplace catalog.
SKILLS_ENABLE_MARKETPLACE: bool = _env_bool("PALIMIND_SKILLS_ENABLE_MARKETPLACE", True)

# Maximum length (chars) of a skill's instruction block (validation guard).
SKILL_MAX_INSTRUCTIONS: int = _env_int("PALIMIND_SKILL_MAX_INSTRUCTIONS", 20_000)

# ── Phase 4.4: agent planning mode ────────────────────────────────────────

# Default planning mode for new agents: "off" | "review" | "auto".
PLANNING_MODE_DEFAULT: str = _env_str("PALIMIND_PLANNING_MODE", "off") or "off"

# Hard ceiling on generated plan steps.
PLAN_MAX_STEPS: int = _env_int("PALIMIND_PLAN_MAX_STEPS", 30)

# Seconds to wait for the user to approve a plan in "review" mode.
PLAN_REVIEW_TIMEOUT: int = _env_int("PALIMIND_PLAN_REVIEW_TIMEOUT", 900)

# ── Phase 4.5: goals & background tasks ───────────────────────────────────

# Maximum number of live background tasks across all goals.
GOALS_MAX_TASKS: int = _env_int("PALIMIND_GOALS_MAX_TASKS", 50)

# Maximum lifetime (days) of a background task/loop.
GOALS_MAX_DURATION_DAYS: int = _env_int("PALIMIND_GOALS_MAX_DURATION_DAYS", 7)

# Poll interval (seconds) for the background-task runner.
GOALS_TICK: int = _env_int("PALIMIND_GOALS_TICK", 15)

# ── optional X/Twitter API ────────────────────────────────────────────────

# Bearer token for X API v2 recent search. Empty = fall back to the public web
# index (DuckDuckGo site search), which needs no credentials.
X_BEARER_TOKEN: str = (
    _env_str("PALIMIND_X_BEARER_TOKEN", "") or _env_str("X_BEARER_TOKEN", "") or ""
)

# Maximum recent-search results requested from X per query (API max is 100).
X_API_MAX_RESULTS: int = _env_int("PALIMIND_X_API_MAX_RESULTS", 40)

# ── Phase 4.6: self-critique & verification ───────────────────────────────

# Minimum confidence (0..1) for a verified answer to be accepted without a
# retry / human review.
SELF_CRITIQUE_CONFIDENCE_THRESHOLD: float = _env_float("PALIMIND_SELF_CRITIQUE_THRESHOLD", 0.6)

# Bounded automatic retries when verification confidence is below threshold.
SELF_CRITIQUE_MAX_RETRIES: int = _env_int("PALIMIND_SELF_CRITIQUE_MAX_RETRIES", 1)

# Bind address for the API server (loopback-only by default).
SERVER_HOST: str = "127.0.0.1"

# ── Computer use (Linux desktop control) ──────────────────────────────────


def _env_csv(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "")
    if raw.strip():
        return [part.strip() for part in raw.split(",") if part.strip()]
    return default


# Master switch. On by default so the popup works out of the box; set
# PALIMIND_DESKTOP_ENABLE=0 to turn the whole capability off.
DESKTOP_ENABLE: bool = _env_bool("PALIMIND_DESKTOP_ENABLE", True)

# Input backend preference: semantic | xtest | mutter | uinput | auto.
DESKTOP_INPUT_BACKEND: str = _env_str("PALIMIND_DESKTOP_INPUT_BACKEND", "auto") or "auto"

# Screenshot policy: off | on_demand | always. Never automatic per step.
DESKTOP_SCREENSHOT: str = _env_str("PALIMIND_DESKTOP_SCREENSHOT", "on_demand") or "on_demand"

# Observation budgets enforced by the native layer. Chromium/web-content trees
# nest the page content deeper than the old 12-level default, so a shallow cap
# returned browser chrome only. The node budget still bounds tokens; the
# formatter drops structural noise and caps the text it emits.
DESKTOP_MAX_NODES: int = _env_int("PALIMIND_DESKTOP_MAX_NODES", 500)
DESKTOP_MAX_DEPTH: int = _env_int("PALIMIND_DESKTOP_MAX_DEPTH", 40)
DESKTOP_SNAPSHOT_TTL_S: int = _env_int("PALIMIND_DESKTOP_SNAPSHOT_TTL_S", 600)

# Time budgets. Large accessibility trees are slow on the first observation
# (and slower through a cold browser); a five-second default used to return a
# partial tree. Override per call with timeout_ms when needed.
DESKTOP_SNAPSHOT_TIMEOUT_MS: int = _env_int("PALIMIND_DESKTOP_SNAPSHOT_TIMEOUT_MS", 20_000)
DESKTOP_FIND_TIMEOUT_MS: int = _env_int("PALIMIND_DESKTOP_FIND_TIMEOUT_MS", 15_000)

# Follow a mutating action with a bounded observation of the same target and
# report what changed. This turns "delivered_unverified" into actionable
# feedback for the agent. Disable for latency-sensitive runs.
DESKTOP_VERIFY_ACTIONS: bool = _env_bool("PALIMIND_DESKTOP_VERIFY_ACTIONS", True)

# Action rate limit (actions per minute).
DESKTOP_ACTION_RATE: int = _env_int("PALIMIND_DESKTOP_ACTION_RATE", 30)

# App policy. Empty allowlist means "any app on the desktop" (the protected and
# blocked sets still win); a non-empty list narrows it. The native layer
# enforces the same rule.
DESKTOP_ALLOWED_APPS: list[str] = _env_csv("PALIMIND_DESKTOP_ALLOWED_APPS", [])
DESKTOP_BLOCKED_APPS: list[str] = _env_csv(
    "PALIMIND_DESKTOP_BLOCKED_APPS",
    [
        "gnome-shell",
        "gjs-console",
        "plasmashell",
        "kwin_wayland",
        "kwin_x11",
        "mutter",
        "gnome-settings-daemon",
        "gnome-session",
        "polkit",
        "gnome-keyring",
        "kwalletd",
        "palimind",
    ],
)

# Explicit development escape hatch. Never enable this in a packaged build.
DESKTOP_ALLOW_ALL: bool = _env_bool("PALIMIND_DESKTOP_ALLOW_ALL", False)

# Optional explicit path to the palimind-desktop binary.
DESKTOP_BIN: str | None = _env_str("PALIMIND_DESKTOP_BIN")

# Chromium DevTools port for the explicit web-content CDP route.
DESKTOP_CDP_PORT: int = _env_int("PALIMIND_DESKTOP_CDP_PORT", 9222)

# Artifact retention (hours) for on-demand screenshots.
DESKTOP_ARTIFACT_RETENTION_H: int = _env_int("PALIMIND_DESKTOP_ARTIFACT_RETENTION_H", 24)
