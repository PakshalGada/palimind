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

# How many relevant memory entries to inject before a run (lexical recall).
AGENT_MEMORY_RECALL_LIMIT: int = _env_int("PALIMIND_AGENT_MEMORY_RECALL_LIMIT", 8)

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

# ── Phase 4.6: self-critique & verification ───────────────────────────────

# Minimum confidence (0..1) for a verified answer to be accepted without a
# retry / human review.
SELF_CRITIQUE_CONFIDENCE_THRESHOLD: float = _env_float("PALIMIND_SELF_CRITIQUE_THRESHOLD", 0.6)

# Bounded automatic retries when verification confidence is below threshold.
SELF_CRITIQUE_MAX_RETRIES: int = _env_int("PALIMIND_SELF_CRITIQUE_MAX_RETRIES", 1)

# Bind address for the API server (loopback-only by default).
SERVER_HOST: str = "127.0.0.1"
