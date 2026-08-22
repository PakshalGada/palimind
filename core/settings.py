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

# Poll interval (seconds) for the scheduled-agent scheduler tick.
AGENT_SCHEDULER_TICK: int = _env_int("PALIMIND_AGENT_SCHEDULER_TICK", 15)

# How many run-history records to keep per agent.
AGENT_RUN_HISTORY_LIMIT: int = _env_int("PALIMIND_AGENT_RUN_HISTORY_LIMIT", 200)
