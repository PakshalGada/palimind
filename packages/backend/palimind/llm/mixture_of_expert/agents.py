from __future__ import annotations

import contextvars
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from palimind.llm.mixture_of_expert.llm import (
    LLMError,
    llm_chat_safe,
    llm_chat_stream,
    ollama_tools_from_registry,
)
from palimind.llm.mixture_of_expert.planner import (
    build_agent_prompt,
    parse_agent_output,
    parse_tool_call,
)
from palimind.llm.mixture_of_expert.tools import (
    AVAILABLE_TOOLS_DESC,
    TOOL_REGISTRY,
    _register_plugin_tools,
    apply_tool_context,
    call_tool,
    get_todo_items,
)
from palimind.settings import (
    MAX_PARALLEL_TOOLS,
    MOE_CONTEXT_BUDGET_TOKENS,
    MOE_MAX_AGENT_ITERATIONS,
    MOE_NUM_CTX,
    TOOL_ROUTER,
    TOOL_ROUTER_TOP_K,
)


def _report_web_step(
    on_step: Callable[[str], None] | None, tool_name: str, tool_result: str
) -> None:
    if on_step is None or tool_name != "web_search":
        return
    import re
    from urllib.parse import urlparse

    urls = re.findall(r"URL:\s*(https?://[^\s\n]+)", tool_result)
    domains = list(dict.fromkeys([urlparse(u).netloc for u in urls if urlparse(u).netloc]))
    if domains:
        on_step(f"Visited: {', '.join(domains[:3])}")
    else:
        on_step("Gathered web search results")


# Prompt sent to the model once its tool budget is exhausted (or a repetitive
# tool loop is detected) so it synthesizes what it already gathered instead of
# the loop ending with a generic "[Agent timed out]" message.
WRAP_UP_PROMPT = (
    "You have reached your step limit. Stop calling tools. "
    "Provide your FINAL_ANSWER now, using the information you have already gathered."
)

FINAL_SYNTHESIS_PROMPT = (
    WRAP_UP_PROMPT + " Return plain prose only: no tool names, no '[tool call' lines, no brackets."
)

# Hard cap on the size of a tool result fed back into the model context so a
# single huge result cannot blow up the window and stall the loop.
MAX_TOOL_RESULT_CHARS = 8000


def _compact_tool_result(result: Any, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Fit a tool result into the context without losing its conclusion.

    Blind head-truncation often drops the useful part of a long document or
    command output (the tail carries summaries, totals and errors). Keep most
    of the head plus the tail and make the elision explicit so the model knows
    it can call the tool again with a narrower query.
    """
    text = str(result)
    if limit <= 0 or len(text) <= limit:
        return text
    marker_template = (
        "\n\n… [{n} characters elided — narrow the query or read a specific range if needed] …\n\n"
    )
    # Reserve room for the marker, then split the remainder 65/35 head/tail.
    budget = max(0, limit - len(marker_template.format(n=len(text))))
    head_len = int(budget * 0.65)
    tail_len = max(0, budget - head_len)
    omitted = len(text) - head_len - tail_len
    marker = marker_template.format(n=omitted)
    compacted = f"{text[:head_len]}{marker}{text[-tail_len:] if tail_len else ''}"
    if len(compacted) > limit:
        compacted = compacted[:limit]
    return compacted


# ── context management ────────────────────────────────────────────────────


def _estimated_tokens(texts: list[str]) -> int:
    """Cheap token approximation (chars / 4), good enough for budgeting."""
    return sum(max(1, len(t) // 4) for t in texts)


def _condense_pair(assistant_msg: dict, user_msg: dict) -> str:
    a = (assistant_msg.get("content") or "").replace("\n", " ")[:140]
    u = (user_msg.get("content") or "").replace("\n", " ")[:260]
    return f"- {a} -> {u}"


def _compact_context(
    live: list[dict],
    working_notes: list[str],
    budget_tokens: int,
) -> list[str]:
    """Pop the oldest assistant/user exchanges off ``live`` and condense them
    into ``working_notes`` until the live region fits the token budget.

    System and task messages live outside ``live`` and are never touched.
    """
    notes = list(working_notes)
    while (
        len(live) >= 2 and _estimated_tokens([m.get("content", "") for m in live]) > budget_tokens
    ):
        notes.append(_condense_pair(live[0], live[1]))
        del live[0:2]
    return notes


def _chat_messages(
    base: list[dict],
    live: list[dict],
    working_notes: list[str],
) -> list[dict]:
    """Assemble the message list sent to the model: system + task, an optional
    condensed working-notes block, then the live exchange window."""
    if not working_notes:
        return base + live
    notes_block = "WORKING NOTES (condensed earlier tool history):\n" + "\n".join(working_notes)
    return base + [{"role": "system", "content": notes_block}] + live


def _budget_for_sub_task(sub_task: dict[str, Any], hard_cap: int) -> int:
    """Adaptive per-agent tool-iteration budget from the plan.

    Base 8; +2 when compute/file tools are present (they need edit loops),
    +2 when web research is involved (fetch-and-read cycles). Clamped so the
    total never exceeds the configured hard cap.
    """
    tools = set(sub_task.get("tools", []))
    budget = 8
    if tools & {"run_python", "write_file"}:
        budget += 2
    if "web_search" in tools:
        budget += 2
    return min(max(budget, 4), max(hard_cap, 4))


def _tool_signature(tool_name: str, tool_args: dict[str, Any] | None) -> str:
    import json

    try:
        args = json.dumps(tool_args or {}, sort_keys=True)
    except (TypeError, ValueError):
        args = str(tool_args or {})
    return f"{tool_name}:{args}"


# Tools where repeated calls usually mean the model is wandering rather than
# making progress. Progress tools (todo_write, read_file, edits) are excluded:
# several checklist updates or reads in a row are often legitimate.
_REPEAT_SENSITIVE_TOOLS = {
    "web_search",
    "fetch_url",
    "browse_url",
    "x_search",
    "arxiv_search",
    "document_search",
}


_INTERNAL_OPENERS = (
    "i will",
    "i'll",
    "let me",
    "next i",
    "now i",
    "i need to",
    "i am going to",
    "i'm going to",
)

_NON_FINAL_MARKERS = (
    "still working",
    "working on it",
    "i am still",
    "let me continue",
    "i will continue",
)

_SYNTHETIC_PREFIXES = (
    "using ",
    "calling ",
    "called ",
    "tool call",
    "[tool call",
)


def _looks_internal(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered[:240] for marker in _NON_FINAL_MARKERS)


def _final_answer_candidate(response: str) -> str:
    """Return a final answer from a model response, or an empty string.

    Native-tool models often answer naturally without the text-protocol
    ``FINAL_ANSWER:`` marker. Reject obvious narration so the loop can nudge
    the model to keep working instead of ending on \"I will search ...\".
    """
    text = (response or "").strip()
    if not text:
        return ""
    if "FINAL_ANSWER:" in text:
        return parse_agent_output(text)
    if "TOOL:" in text or "ARGS:" in text:
        return ""
    lowered = text.lower()
    # Synthetic transcript lines must never become the answer if a model
    # echoes them back (seen with smaller local models).
    if "[tool call:" in lowered[:80]:
        return ""
    if len(text) <= 80 and lowered.startswith(_SYNTHETIC_PREFIXES):
        return ""
    if len(text) < 8:
        return ""
    if lowered.startswith(_INTERNAL_OPENERS) or _looks_internal(text):
        return ""
    if text.endswith(("...", "…", ":")):
        return ""
    return text


def _is_repeating_tool(recent: list[str], repeats: int = 5) -> bool:
    """True when the last *repeats* calls were the same search-style tool.

    Exact-argument loops are caught by :func:`_is_looping`; this catches the
    more common research failure where the model keeps re-searching with
    slightly different queries and never synthesises.
    """
    if len(recent) < repeats:
        return False
    names = [signature.split(":", 1)[0] for signature in recent[-repeats:]]
    return bool(names[0]) and len(set(names)) == 1 and names[0] in _REPEAT_SENSITIVE_TOOLS


def _is_looping(recent: list[str], repeats: int = 3) -> bool:
    """Return True when the exact same tool+args call appears repeatedly.

    Models occasionally get stuck re-invoking the same tool with identical
    arguments, which burns the whole iteration budget. When detected we stop
    calling tools and force a synthesis step instead.
    """
    if len(recent) < repeats:
        return False
    sig = recent[-1]
    count = sum(1 for s in recent[-max(repeats, len(recent)) :] if s == sig)
    return count >= repeats


# ── custom-agent (definition-based) support ───────────────────────────────

# Tools that mutate state and may require human-in-the-loop approval.
RISKY_TOOLS = {
    "write_file",
    "run_python",
    "search_replace",
    "run_shell",
    # Browser interactions can submit forms / trigger side effects.
    "browser_click",
    "browser_type",
    "browser_press",
    # Desktop actions can click Send/Delete/Purchase in any app.
    "desktop_act",
    "desktop_launch",
    "desktop_screenshot",
}

# Irreversible / externally-visible actions used by "high autonomy".
HIGH_RISK_TOOLS = {
    "run_shell",
    "run_python",
    "browser_click",
    "browser_type",
    "browser_press",
    "desktop_act",
    "desktop_launch",
}

# File-changing tools that should be followed by a verification step before
# the agent answers. Grok-class agents verify edits; local models often do not.
FILE_MUTATION_TOOLS = {
    "write_file",
    "search_replace",
    "apply_patch",
    "docx_write",
    "pptx_write",
    "xlsx_write",
    "pdf_merge",
    "pdf_split",
    "pdf_rotate",
}
VERIFICATION_TOOLS = {"read_file", "run_python", "run_shell", "grep_files", "glob_files"}

VERIFY_AFTER_EDIT_PROMPT = (
    "You just changed files. Before FINAL_ANSWER, verify the change by reading "
    "the affected file or running a check, then report what you verified."
)

_WORK_HINTS = (
    "research",
    "compare",
    "find",
    "read",
    "write",
    "fix",
    "create",
    "build",
    "analy",
    "investigate",
    "report",
    "check",
    "update",
    "summar",
)


def _task_needs_tools(task: str, has_work_tools: bool) -> bool:
    if not has_work_tools:
        return False
    text = (task or "").lower()
    return len(text) > 80 or any(hint in text for hint in _WORK_HINTS)


def _verification_reminder(tool_names: list[str]) -> str:
    """Return a verification prompt when a batch edited files without checking."""
    changed = [name for name in tool_names if name in FILE_MUTATION_TOOLS]
    if not changed:
        return ""
    if any(name in VERIFICATION_TOOLS for name in tool_names):
        return ""
    return VERIFY_AFTER_EDIT_PROMPT


# Definition-less (MoE) runs may not silently mutate the workspace: these
# require an approval flow. Isolated compute (run_python) stays allowed.
MOE_MUTATION_TOOLS = {"write_file", "search_replace", "run_shell"}

# tier_policy -> allowed tool tiers (tier 1 read-only, 2 write/execute, 3 privileged)
TIER_POLICY_ALLOWED = {
    "tier1": {1},
    "tier1+2": {1, 2},
    "all": {1, 2, 3},
}


def _tool_tier(tool_name: str) -> int:
    info = TOOL_REGISTRY.get(tool_name, {})
    return int((info.get("meta") or {}).get("tier", 3))


def _emit_event(event_cb: Callable[[str, dict], Any] | None, etype: str, payload: dict) -> None:
    """Best-effort structured event emission (SSE reasoning chain)."""
    if event_cb is None:
        return
    try:
        event_cb(etype, payload)
    except Exception as e:
        print(f"[Agent] event emit failed ({etype}): {e}")


# Final answers are emitted as chunked `agent:token` events so the UI can
# render them progressively. Chunk size trades event volume (each crossing the
# sync→async bridge) against smoother streaming.
_TOKEN_CHUNK_CHARS = 200


def _emit_tokens(event_cb: Callable[[str, dict], Any] | None, text: str) -> None:
    if event_cb is None or not text:
        return
    for i in range(0, len(text), _TOKEN_CHUNK_CHARS):
        _emit_event(event_cb, "agent:token", {"text": text[i : i + _TOKEN_CHUNK_CHARS]})


def _normalize_app(value: str) -> str:
    stem = value.strip().lower().rsplit("/", 1)[-1]
    if stem.endswith(".desktop"):
        stem = stem[: -len(".desktop")]
    return "".join(ch if ch.isalnum() else "-" for ch in stem).strip("-")


def _desktop_app_allowed(app: str, allowed: list[str]) -> bool:
    """Match an app name/desktop id against a per-agent allowlist.

    Mirrors the native policy: exact, executable basename, and suffix-token
    matches (``calculator`` allows ``gnome-calculator`` and
    ``org.gnome.Calculator``).
    """

    candidate = _normalize_app(app)
    for pattern in allowed:
        normalized = _normalize_app(pattern)
        if not normalized:
            continue
        if (
            candidate == normalized
            or candidate.endswith("-" + normalized)
            or normalized.endswith("-" + candidate)
        ):
            return True
    return False


def _gate_tool(
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    definition: Any | None = None,
    approval_provider: Callable[[dict], dict] | None = None,
    response: str = "",
) -> str | None:
    """Return a denial-reason string if the tool call must be blocked.

    For definition-driven agents: enforces tier_policy and the write/shell
    access flags, then consults ``approval_provider`` for risky tools when a
    HITL threshold is configured. For definition-less (MoE) runs, file
    mutations require an approval flow; without one they are denied so MoE
    cannot silently overwrite the workspace. Returns None when the call may
    proceed.
    """
    if definition is not None:
        # tier_policy gate
        policy = getattr(definition, "tier_policy", "tier1+2") or "tier1+2"
        allowed = TIER_POLICY_ALLOWED.get(policy, TIER_POLICY_ALLOWED["tier1+2"])
        if _tool_tier(tool_name) not in allowed:
            return (
                f"Access denied: tool '{tool_name}' is tier {_tool_tier(tool_name)} "
                f"but this agent's tier_policy is '{policy}'"
            )

        # access-flag gates
        if tool_name in ("write_file", "search_replace") and not getattr(
            definition, "write_access", True
        ):
            return f"Access denied: this agent does not have write_access ('{tool_name}' blocked)"
        if tool_name in ("run_python", "run_shell") and not getattr(
            definition, "shell_access", True
        ):
            return f"Access denied: this agent does not have shell_access ('{tool_name}' blocked)"

        # Computer use: observation and mutation are separate grants. The
        # native layer re-checks the app allowlist, but a per-agent allowlist
        # narrows it further here before any RPC is made.
        if tool_name.startswith("desktop_"):
            if not getattr(definition, "desktop_access", False):
                return (
                    f"Access denied: this agent does not have desktop_access "
                    f"('{tool_name}' blocked)"
                )
            if tool_name in ("desktop_act", "desktop_launch", "desktop_screenshot") and not getattr(
                definition, "desktop_control", False
            ):
                return (
                    f"Access denied: this agent does not have desktop_control "
                    f"('{tool_name}' blocked)"
                )
            allowed_apps = getattr(definition, "desktop_allowed_apps", []) or []
            target_app = str(tool_args.get("app") or "").strip()
            if allowed_apps and target_app and not _desktop_app_allowed(target_app, allowed_apps):
                return f"Access denied: '{target_app}' is not in this agent's desktop_allowed_apps"

        # Per-tool policy override (allow / ask / deny).
        policies = getattr(definition, "tool_policies", {}) or {}
        decision = str(policies.get(tool_name, "") or "").lower()
        if decision == "deny":
            return (
                f"Access denied: this agent's tool policy blocks '{tool_name}'. "
                "Ask the user to change it in the agent settings."
            )
        if decision == "allow":
            return None

        # Autonomy gate.
        autonomy = str(getattr(definition, "autonomy_level", "") or "")
        if not autonomy:
            # Backward compatibility for legacy definition-like objects.
            try:
                legacy_threshold = float(getattr(definition, "human_in_loop_threshold", 0.0) or 0.0)
            except (TypeError, ValueError):
                legacy_threshold = 0.0
            autonomy = "off" if legacy_threshold <= 0 else "semi"
        if autonomy == "off":
            return None
        # Explicit always-allow tools skip the approval prompt (but tier and
        # access-flag gates above still apply).
        always_allow = getattr(definition, "always_allow_tools", []) or []
        if tool_name in always_allow:
            return None
        if autonomy == "supervised":
            needs_approval = True
        elif autonomy == "high":
            needs_approval = _tool_tier(tool_name) >= 3 or tool_name in HIGH_RISK_TOOLS
        else:  # semi-autonomous (default)
            needs_approval = tool_name in RISKY_TOOLS or _tool_tier(tool_name) >= 2

        if needs_approval:
            if approval_provider is None:
                return (
                    f"Access denied: '{tool_name}' needs human approval under this "
                    "agent's autonomy level, but this run has no approval channel. "
                    "Start it from the UI or lower the autonomy requirement."
                )
            return _request_approval(tool_name, tool_args, approval_provider, response)
        return None

    # ── definition-less (MoE) runs ─────────────────────────────────────
    # Isolated compute stays allowed; file mutations and shell execution must
    # be explicitly approved, mirroring named-agent write_access/HITL.
    # Desktop tools are definition-gated: a definition-less run has no
    # desktop_access/desktop_control grant and cannot observe or act.
    if tool_name.startswith("desktop_"):
        return (
            f"Access denied: '{tool_name}' needs a configured agent with "
            "desktop_access/desktop_control and an app allowlist"
        )
    if tool_name in MOE_MUTATION_TOOLS:
        if approval_provider is None:
            return (
                f"Access denied: '{tool_name}' mutates the workspace and requires "
                "human approval. Use a configured agent with write/shell access, or "
                "approve the action in the UI."
            )
        return _request_approval(tool_name, tool_args, approval_provider, response)
    return None


def _request_approval(
    tool_name: str,
    tool_args: dict[str, Any],
    approval_provider: Callable[[dict], dict],
    response: str,
) -> str | None:
    try:
        result = approval_provider(
            {
                "tool": tool_name,
                "args": tool_args,
                "confidence": 0.0,
                "threshold": 0.0,
                "reasoning": (response or "")[:300],
            }
        )
        approved = bool((result or {}).get("approved"))
        correction = (result or {}).get("correction", "")
        override = (result or {}).get("args")
        if approved and isinstance(override, dict):
            # Edit-before-run: replace the complete argument object. call_tool
            # validates it again against the tool schema before executing.
            tool_args.clear()
            tool_args.update(override)
        if not approved:
            reason = "the human reviewer rejected this action"
            if correction:
                reason += f' with feedback: "{correction}"'
            return f"Human reviewer rejected '{tool_name}': {reason}"
    except Exception as e:
        return f"Approval flow error for '{tool_name}': {e}"
    return None


CANCELLED_ANSWER = "[Agent run cancelled]"


def _is_cancelled(run_control: Any | None) -> bool:
    """True once the owning run was stopped (no-op without a run_control)."""
    if run_control is None:
        return False
    flag = getattr(run_control, "cancelled", None)
    try:
        return bool(flag is not None and flag.is_set())
    except Exception:
        return False


def run_agent(
    agent_id: int,
    sub_task: dict[str, Any],
    worker_model: str,
    ollama_url: str,
    max_tool_iterations: int | None = None,
    on_step: Callable[[str], None] | None = None,
    definition: Any | None = None,
    extra_system_prompt: str = "",
    event_cb: Callable[[str, dict], Any] | None = None,
    approval_provider: Callable[[dict], dict] | None = None,
    session_id: str = "",
    briefing: str = "",
    usage_cb: Callable[[dict], None] | None = None,
    token_stream: bool = False,
    reflect: bool = False,
    tool_context: dict[str, Any] | None = None,
    run_control: Any | None = None,
    run_id: str = "",
    resume_state: dict[str, Any] | None = None,
    resume_from_run_id: str = "",
    escalation_model: str = "",
    escalation_url: str = "",
    escalation_max_cost_usd: float = 0.0,
    model_client: Callable[..., dict[str, Any]] | None = None,
) -> str:
    """Run one agent loop.

    The first six parameters are the original MoE worker interface. The
    keyword parameters support definition-driven custom agents
    (palimind.agents.runtime.run_with_definition):

    - ``definition``: AgentDefinition — supplies temperature, tool-access
      flags (write_access/shell_access) and human_in_loop_threshold.
    - ``extra_system_prompt``: appended to the built-in system prompt
      (custom persona + [AGENT MEMORY] block).
    - ``event_cb``: sync callback for structured events:
      agent:thought / agent:tool_call / agent:tool_result.
    - ``approval_provider``: blocking callback consulted before risky tools
      (write_file, run_python) when the HITL threshold > 0; returns
      {"approved": bool, "correction": str}.
    - ``session_id``: optional correlation id (logged only).
    - ``briefing``: shared pre-searched context injected into the task
      prompt so every agent starts with the same findings (no duplicate
      turn-0 web searches).
    - ``usage_cb``: invoked once with accumulated token counts.
    - ``token_stream``: when True and ``event_cb`` is set, stream the final
      answer live from the model as ``agent:token`` events (with a ``reset``
      event if streamed text turns out to be internal reasoning).
    - ``escalation_model`` / ``escalation_url``: optional stronger model used
      once for the final synthesis when the step budget is exhausted. Emits an
      ``agent:escalation`` event before the call.
    - ``escalation_max_cost_usd``: optional cost ceiling. When the run's
      accumulated cost reaches it, escalation is skipped and the event records
      why (0 disables the ceiling).
    - token usage is emitted as ``agent:usage`` after every model call so the
      live UI can show prompt/completion counts and an estimated cost.
    """
    _register_plugin_tools()
    if tool_context is not None:
        # Each worker installs its own context in its own thread; never rely
        # on a process-global set by the orchestrator.
        apply_tool_context({**tool_context, "agent_id": str(agent_id), "session_id": session_id})

    if max_tool_iterations is None:
        max_tool_iterations = _budget_for_sub_task(sub_task, MOE_MAX_AGENT_ITERATIONS)

    # The definition's context_budget (tokens) caps the live exchange window;
    # fall back to the global MoE budget, never below a usable floor.
    ctx_budget = int(getattr(definition, "context_budget", 0) or 0) or MOE_CONTEXT_BUDGET_TOKENS
    ctx_budget = max(1000, ctx_budget)

    # Set True once the final answer has been streamed live, so the caller
    # does not emit it a second time as chunked tokens.
    streamed_answer = [False]

    allowed_tools = [t for t in sub_task.get("tools", []) if t in TOOL_REGISTRY]
    # An empty allowlist means "unrestricted" (legacy MoE behaviour): route from
    # the full registry instead of showing only the discovery tool.
    visible_tools = list(allowed_tools or TOOL_REGISTRY.keys())
    if TOOL_ROUTER and visible_tools:
        from palimind.agents.tool_router import select_tools

        visible_tools = select_tools(
            str(sub_task.get("task", "")),
            visible_tools,
            TOOL_REGISTRY,
            top_k=max(1, int(TOOL_ROUTER_TOP_K or 12)),
            pinned=sub_task.get("pinned_tools") or None,
        )
    # Discovery and the run checklist must always be reachable, even when the
    # agent uses a strict pack.
    for must_have in ("tool_search", "todo_write", "ask_user"):
        if must_have in TOOL_REGISTRY and must_have not in visible_tools:
            visible_tools.append(must_have)

    native_tools = (
        ollama_tools_from_registry({name: TOOL_REGISTRY[name] for name in visible_tools})
        if visible_tools
        else None
    )

    temperature = getattr(definition, "temperature", None) if definition else None

    system_prompt = f"""You are Agent {agent_id}, an expert in a Mixture-of-Experts system.
You execute assigned sub-tasks using available tools.

Available tools:
{AVAILABLE_TOOLS_DESC if not visible_tools else chr(10).join(f"- {t}: {TOOL_REGISTRY[t]['description']}" for t in visible_tools)}

Use tool_search when you need a capability that is not listed above. The full
tool allowlist is still enforced even if a tool is not shown.

When native tool calls are available, call tools directly.

Otherwise, to use a tool, respond with:
  TOOL: tool_name
  ARGS: key1=value1, key2=value2
(ARGS may also be a JSON object on one line.)

When your task is complete, respond with:
  FINAL_ANSWER:
  <your final answer>

Before the first tool call in any task that needs two or more tool calls,
call todo_write with a short checklist. Keep it to 2-7 concrete items, mark
exactly one in_progress, and mark each item completed as you finish it. Do not
give FINAL_ANSWER while an item is still pending or in_progress.

Checklist updates are bookkeeping, not progress. After creating the list,
immediately call the real tool for the current item (web_search, fetch_url,
read_file, search_replace, run_python, …). Never call todo_write twice in a row
without a work tool in between.

If a decision, missing detail or credential genuinely blocks the task, call
ask_user with one short question and a few concrete options, then continue with
the answer. Do not ask for information you can find with a tool.

Be concise and effective."""

    if extra_system_prompt:
        system_prompt = f"{system_prompt}\n\n{extra_system_prompt}"

    base = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": build_agent_prompt(agent_id, sub_task, worker_model, briefing=briefing),
        },
    ]
    live: list[dict] = []
    working_notes: list[str] = []
    full_log: list[str] = []
    recent_tool_calls: list[str] = []
    read_files: set[str] = set()
    todo_nudges = 0
    verify_nudges = 0
    work_nudges = 0
    closeout_used = False
    mutated_since_verify = False
    work_tool_calls = 0
    has_work_tools = any(
        name not in ("todo_write", "tool_search", "ask_user") for name in visible_tools
    )
    start_iteration = 0

    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}

    def _track(result: dict) -> None:
        u = result.get("usage") or {}
        usage["prompt_tokens"] += int(u.get("prompt_tokens", 0))
        usage["completion_tokens"] += int(u.get("completion_tokens", 0))
        _emit_event(
            event_cb,
            "agent:usage",
            {
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
            },
        )

    from palimind.agents.failover import FailoverGate, classify_failure, should_failover

    failover_gate = FailoverGate()

    def _result_failed(result: dict[str, Any]) -> bool:
        text = str(result.get("content") or "")
        return text.startswith("[Agent ") and " error:" in text

    def _try_failover(
        msgs: list[dict[str, str]],
        failure_text: str,
        tools: list[dict] | None,
    ) -> dict[str, Any] | None:
        backups = list(getattr(definition, "backup_models", []) or []) if definition else []
        if not backups:
            return None
        cause = classify_failure(failure_text)
        acted = bool(live)
        if not should_failover(cause=cause, acted=acted, has_backup=True):
            return None
        primary = {
            "provider": str(getattr(definition, "provider", "") or ""),
            "model": worker_model,
        }
        chosen = failover_gate.choose(primary, backups)
        if chosen is None:
            return None
        backup_model = str(chosen.get("model") or chosen.get("id") or "")
        if not backup_model:
            return None
        failover_gate.hold(str((primary.get("provider") or "") + "/" + worker_model))
        backup_url = ollama_url
        try:
            from palimind.opencode.router import resolve_model_url

            backup_url = resolve_model_url(backup_model, backup_url)
        except Exception:
            pass
        _emit_event(
            event_cb,
            "agent:failover",
            {
                "from": worker_model,
                "to": backup_model,
                "cause": cause,
                "provider": str(chosen.get("provider") or ""),
            },
        )
        client = model_client
        if client is None:
            from palimind.llm.mixture_of_expert.llm import llm_chat_safe

            client = llm_chat_safe
        result = client(
            msgs,
            backup_model,
            backup_url,
            tools=tools,
            error_prefix=f"[Agent {agent_id} error",
            temperature=temperature,
            num_ctx=MOE_NUM_CTX,
        )
        if _result_failed(result):
            failover_gate.hold(backup_model)
            return None
        _track(result)
        return result

    def _call(
        tools: list[dict] | None,
        extra_user: str | None = None,
        stream_mode: str | None = None,
        *,
        model_override: str = "",
        url_override: str = "",
    ) -> dict[str, Any]:
        """Call the worker model.

        ``stream_mode``:
          - ``None``         — non-streaming (retrying) call.
          - ``"detect"``     — stream but only surface tokens once the
                               ``FINAL_ANSWER:`` marker appears.
          - ``"always"``     — stream every token (used for the forced
                               wrap-up synthesis, where tools are disabled).
        """
        msgs = _chat_messages(base, live, working_notes)
        if extra_user:
            msgs = msgs + [{"role": "user", "content": extra_user}]

        call_model = model_override or worker_model
        call_url = url_override or ollama_url

        # A hosted/OpenAI client is non-streaming here; the final answer is
        # still emitted in chunks by _finalize, so the UI contract is intact.
        if model_client is not None or not (token_stream and stream_mode):
            client = model_client or llm_chat_safe
            result = client(
                msgs,
                call_model,
                call_url,
                tools=tools,
                error_prefix=f"[Agent {agent_id} error",
                temperature=temperature,
                num_ctx=MOE_NUM_CTX,
            )
            if _result_failed(result):
                failed_text = str(result.get("content") or "")
                alt = _try_failover(msgs, failed_text, tools)
                if alt is not None:
                    return alt
            _track(result)
            return result

        from palimind.settings import LLM_RETRIES

        marker = "FINAL_ANSWER:"
        content = ""
        tool_calls: list[dict[str, Any]] = []
        call_usage: dict[str, int] = {}
        emitting = stream_mode == "always"
        if emitting:
            streamed_answer[0] = True

        for attempt in range(LLM_RETRIES + 1):
            try:
                for ev in llm_chat_stream(
                    msgs,
                    call_model,
                    call_url,
                    tools=tools,
                    temperature=temperature,
                    num_ctx=MOE_NUM_CTX,
                ):
                    if ev["type"] == "token":
                        content += ev["text"]
                        if not emitting and marker in content:
                            tail = content.split(marker, 1)[1]
                            if tail:
                                emitting = True
                                streamed_answer[0] = True
                                _emit_event(event_cb, "agent:token", {"text": tail, "stream": True})
                        elif emitting:
                            _emit_event(
                                event_cb, "agent:token", {"text": ev["text"], "stream": True}
                            )
                    elif ev["type"] == "tool_calls":
                        tool_calls = ev["tool_calls"]
                    elif ev["type"] == "usage":
                        call_usage = ev["usage"]
                break
            except LLMError as e:
                if e.transient and attempt < LLM_RETRIES and not content:
                    time.sleep(min(0.5 * (2**attempt), 4.0))
                    continue
                if emitting:
                    _emit_event(event_cb, "agent:token", {"reset": True})
                    streamed_answer[0] = False
                alt = _try_failover(msgs, str(e), tools)
                if alt is not None:
                    text = str(alt.get("content") or "")
                    if text and event_cb is not None:
                        _emit_event(event_cb, "agent:token", {"text": text, "stream": True})
                        streamed_answer[0] = True
                    return alt
                return {
                    "content": f"[Agent {agent_id} error: {e}]",
                    "tool_calls": [],
                    "usage": {},
                }

        # Streamed text that accompanied a tool call was internal reasoning.
        if emitting and tool_calls:
            _emit_event(event_cb, "agent:token", {"reset": True})
            streamed_answer[0] = False

        result = {"content": content, "tool_calls": tool_calls, "usage": call_usage}
        _track(result)
        return result

    def _reflect_answer(draft: str) -> str:
        """One extra LLM pass that critiques and improves the draft answer."""
        task = str(sub_task.get("task", ""))
        client = model_client or llm_chat_safe
        result = client(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a meticulous reviewer. Critique the draft answer for "
                        "correctness, completeness and clarity, then output an improved "
                        "final answer. Do not mention the critique or this instruction — "
                        "output only the improved answer."
                    ),
                },
                {"role": "user", "content": f"TASK:\n{task}\n\nDRAFT ANSWER:\n{draft}"},
            ],
            worker_model,
            ollama_url,
            error_prefix=f"[Agent {agent_id} reflection error",
            temperature=temperature,
            num_ctx=MOE_NUM_CTX,
        )
        _track(result)
        refined = (result.get("content") or "").strip()
        if "FINAL_ANSWER:" in refined:
            refined = parse_agent_output(refined)
        return refined

    def _close_leftover_checklist(answer: str) -> None:
        """Close bookkeeping left open by the model after a real answer.

        The loop already nudges once for the model to finish its own checklist.
        When the final answer is delivered and items are still open, the runtime
        closes them so the UI never shows a finished run with stale work, and
        records that the closeout was automatic.
        """
        if not answer or answer.startswith("[Agent"):
            return
        try:
            open_items = [item for item in get_todo_items() if item.get("status") != "completed"]
            if not open_items:
                return
            from palimind.llm.mixture_of_expert.tools import todo_write

            todo_write([{**item, "status": "completed"} for item in get_todo_items()])
            _emit_event(
                event_cb,
                "agent:todo",
                {"items": get_todo_items(), "closed_by": "runtime_finalize"},
            )
        except Exception as exc:  # noqa: BLE001 - bookkeeping must not lose the answer
            print(f"[agents] checklist closeout failed: {exc}")

    def _finalize(answer: str) -> str:
        """Optionally self-critique, then emit the final answer exactly once."""
        _close_leftover_checklist(answer)
        if reflect:
            _emit_event(event_cb, "agent:thought", {"text": "Reflecting on the answer…"})
            refined = _reflect_answer(answer)
            if refined and not refined.startswith("[Agent "):
                answer = refined
            if streamed_answer[0]:
                _emit_event(event_cb, "agent:token", {"reset": True})
            _emit_tokens(event_cb, answer)
            streamed_answer[0] = True
        elif not streamed_answer[0]:
            _emit_tokens(event_cb, answer)
        _finish_usage()
        return answer

    def _finish_usage() -> None:
        if usage_cb is not None:
            usage_cb(dict(usage))

    def _cancelled_result(iteration: int = 0) -> str:
        # Stop requested: end the run without another LLM/tool call.
        _finish_usage()
        _checkpoint(iteration, status="cancelled", output=CANCELLED_ANSWER)
        return CANCELLED_ANSWER

    def _checkpoint(iteration: int, status: str = "running", output: str = "") -> None:
        if not run_id:
            return
        try:
            from palimind.agents import run_state as run_state_mod

            run_state_mod.save_state(
                {
                    "run_id": run_id,
                    "agent_id": str(
                        sub_task.get("definition_id") or sub_task.get("agent_id") or agent_id
                    ),
                    "input": str(sub_task.get("task") or ""),
                    "session_id": session_id,
                    "model": worker_model,
                    "ollama_url": ollama_url,
                    "messages": live,
                    "working_notes": working_notes,
                    "recent_tool_calls": recent_tool_calls,
                    "full_log": full_log,
                    "usage": usage,
                    "iteration": iteration,
                    "status": status,
                    "output": output,
                    "resumed_from": resume_from_run_id,
                }
            )
        except Exception as exc:  # noqa: BLE001 - checkpointing must never kill a run
            print(f"[agents] checkpoint failed for {run_id}: {exc}")

    if resume_state:
        live = [
            {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")}
            for m in (resume_state.get("messages") or [])
            if isinstance(m, dict)
        ]
        working_notes = [
            str(n) for n in (resume_state.get("working_notes") or []) if str(n).strip()
        ]
        recent_tool_calls = [str(s) for s in (resume_state.get("recent_tool_calls") or [])]
        full_log = [str(line) for line in (resume_state.get("full_log") or [])]
        saved_usage = resume_state.get("usage") or {}
        usage["prompt_tokens"] = int(saved_usage.get("prompt_tokens", 0) or 0)
        usage["completion_tokens"] = int(saved_usage.get("completion_tokens", 0) or 0)
        start_iteration = max(0, int(resume_state.get("iteration", 0) or 0))
        if resume_from_run_id:
            try:
                from palimind.agents import run_state as run_state_mod

                run_state_mod.mark_resumed(resume_from_run_id, run_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[agents] failed to mark {resume_from_run_id} resumed: {exc}")

    _checkpoint(start_iteration)

    for iteration in range(start_iteration, max_tool_iterations):
        if run_control is not None:
            while getattr(run_control, "paused", None) is not None and run_control.paused.is_set():
                time.sleep(0.1)
            try:
                for steer_text in run_control.drain_steer():
                    live.append(
                        {
                            "role": "user",
                            "content": f"The user adds: {steer_text}\nAcknowledge and adjust your work.",
                        }
                    )
                    _emit_event(
                        event_cb,
                        "agent:thought",
                        {"text": f"Steering: {steer_text[:300]}", "iteration": iteration},
                    )
            except Exception:
                pass
            try:
                plan_override = run_control.drain_plan()
                if plan_override is not None:
                    from palimind.llm.mixture_of_expert.tools import (
                        get_todo_items as _get_todo_items,
                    )
                    from palimind.llm.mixture_of_expert.tools import (
                        set_todo_items as _set_todo_items,
                    )

                    _set_todo_items(plan_override)
                    live.append(
                        {
                            "role": "user",
                            "content": (
                                "[CHECKLIST UPDATED BY USER] Follow this checklist exactly; "
                                "do not rewrite it unless the work genuinely changes.\n"
                                + "\n".join(
                                    f"- [{item['status']}] {item['label']}"
                                    for item in _get_todo_items()
                                )
                            ),
                        }
                    )
                    _emit_event(
                        event_cb,
                        "agent:todo",
                        {"items": _get_todo_items(), "source": "user", "iteration": iteration},
                    )
            except Exception:
                pass
        if _is_cancelled(run_control):
            return _cancelled_result(iteration)
        if iteration > start_iteration and _is_repeating_tool(recent_tool_calls):
            _emit_event(
                event_cb,
                "agent:thought",
                {
                    "text": "Repeated the same tool several times — synthesizing already gathered results.",
                    "iteration": iteration,
                },
            )
            break
        if iteration > start_iteration and iteration >= max_tool_iterations - 1:
            open_items = [item for item in get_todo_items() if item.get("status") != "completed"]
            if open_items and not closeout_used:
                # Spend the reserved synthesis step closing the checklist, then
                # let the wrap-up produce the answer on the next pass.
                closeout_used = True
                labels = ", ".join(str(item.get("label", "")) for item in open_items[:5])
                _emit_event(
                    event_cb,
                    "agent:thought",
                    {
                        "text": "Step limit near — closing the checklist before the final answer.",
                        "iteration": iteration,
                    },
                )
                live.append(
                    {
                        "role": "user",
                        "content": (
                            "Before the final answer, call todo_write and mark every "
                            f"completed item done. Open items: {labels}. Only keep an item "
                            "open if it genuinely was not done, and explain why in the answer."
                        ),
                    }
                )
            else:
                # Reserve the final step for synthesis instead of spending it on
                # another tool call that cannot be followed up.
                _emit_event(
                    event_cb,
                    "agent:thought",
                    {
                        "text": "Approaching the step limit — reserving a synthesis pass.",
                        "iteration": iteration,
                    },
                )
                break
        result = _call(native_tools, stream_mode="detect" if token_stream else None)
        response = result["content"]
        _emit_event(
            event_cb, "agent:thought", {"text": (response or "")[:2000], "iteration": iteration}
        )

        # ── 1. Native tool calls (preferred) ──────────────────────────
        if result["tool_calls"]:
            if _is_cancelled(run_control):
                return _cancelled_result(iteration)
            batch = _execute_tool_batch(
                agent_id,
                list(result["tool_calls"]),
                sub_task,
                on_step,
                full_log,
                definition=definition,
                approval_provider=approval_provider,
                response=response,
                event_cb=event_cb,
                run_control=run_control,
                read_files=read_files,
            )
            # OpenAI-compatible providers require the canonical transcript:
            # one assistant message carrying all tool_calls (with ids), then
            # one role=tool result per id. Ollama-style calls have no id and
            # keep the compact user-message transcript.
            openai_calls = [tc for tc in result["tool_calls"] if tc.get("openai")]
            if openai_calls:
                live.append(
                    {
                        "role": "assistant",
                        "content": response or "",
                        "tool_calls": [
                            {
                                "id": str(tc["id"]),
                                "type": "function",
                                "function": {
                                    "name": str(tc.get("name") or ""),
                                    "arguments": json.dumps(tc.get("arguments") or {}),
                                },
                            }
                            for tc in openai_calls
                        ],
                    }
                )
            for tc, tool_result in batch:
                call_name = str(tc.get("name") or "")
                native_args = {k: v for k, v in (tc.get("arguments") or {}).items()}
                if tc.get("openai") and tc.get("id"):
                    live.append(
                        {
                            "role": "tool",
                            "tool_call_id": str(tc["id"]),
                            "content": _compact_tool_result(tool_result),
                        }
                    )
                else:
                    # Keep the synthetic line explicit: _final_answer_candidate
                    # rejects it if a small model echoes it back as an answer.
                    live.append(
                        {"role": "assistant", "content": response or f"[tool call: {call_name}]"}
                    )
                    live.append(
                        {
                            "role": "user",
                            "content": (
                                f"Tool '{call_name}' returned:\n{_compact_tool_result(tool_result)}"
                            ),
                        }
                    )
                recent_tool_calls.append(_tool_signature(call_name, native_args))
            batch_names = [str(tc.get("name") or "") for tc in result["tool_calls"]]
            work_tool_calls += sum(
                1 for name in batch_names if name not in ("todo_write", "tool_search")
            )
            if any(name in FILE_MUTATION_TOOLS for name in batch_names):
                mutated_since_verify = True
            if any(name in VERIFICATION_TOOLS for name in batch_names):
                mutated_since_verify = False
            reminder = _verification_reminder(batch_names)
            if reminder:
                _emit_event(
                    event_cb,
                    "agent:thought",
                    {
                        "text": "Edit made — verifying before the final answer.",
                        "iteration": iteration,
                    },
                )
                live.append({"role": "user", "content": reminder})
            working_notes = _compact_context(live, working_notes, ctx_budget)
            if _is_looping(recent_tool_calls):
                _emit_event(
                    event_cb,
                    "agent:thought",
                    {"text": "Repeated tool call detected — wrapping up.", "iteration": iteration},
                )
                live.append({"role": "assistant", "content": response})
                live.append({"role": "user", "content": WRAP_UP_PROMPT})
            _checkpoint(iteration + 1)
            continue

        # ── 2. Text-protocol tool call (fallback) ─────────────────────
        tool_name, tool_args = parse_tool_call(response)
        if tool_name:
            if _is_cancelled(run_control):
                return _cancelled_result(iteration)
            tool_args = tool_args or {}
            # Same ordering/payloads as the native path: tool_call →
            # allow-list → approval gate → tool_result.
            tool_result = _execute_tool(
                agent_id,
                tool_name,
                tool_args,
                sub_task,
                on_step,
                full_log,
                definition=definition,
                approval_provider=approval_provider,
                response=response,
                event_cb=event_cb,
                read_files=read_files,
            )

            tool_msg = f"Tool '{tool_name}' returned:\n{_compact_tool_result(tool_result)}"
            live.append({"role": "assistant", "content": response})
            live.append({"role": "user", "content": tool_msg})
            recent_tool_calls.append(_tool_signature(tool_name, tool_args))
            if tool_name not in ("todo_write", "tool_search", "ask_user"):
                work_tool_calls += 1
            if tool_name in FILE_MUTATION_TOOLS:
                mutated_since_verify = True
            elif tool_name in VERIFICATION_TOOLS:
                mutated_since_verify = False
            reminder = _verification_reminder([tool_name])
            if reminder:
                _emit_event(
                    event_cb,
                    "agent:thought",
                    {
                        "text": "Edit made — verifying before the final answer.",
                        "iteration": iteration,
                    },
                )
                live.append({"role": "user", "content": reminder})
            working_notes = _compact_context(live, working_notes, ctx_budget)
            if _is_looping(recent_tool_calls):
                _emit_event(
                    event_cb,
                    "agent:thought",
                    {"text": "Repeated tool call detected — wrapping up.", "iteration": iteration},
                )
                live.append({"role": "assistant", "content": response})
                live.append({"role": "user", "content": WRAP_UP_PROMPT})
            _checkpoint(iteration + 1)
            continue

        # ── 3. Final answer ───────────────────────────────────────────
        final_answer = _final_answer_candidate(response)
        if final_answer:
            if mutated_since_verify and verify_nudges < 1:
                verify_nudges += 1
                _emit_event(
                    event_cb,
                    "agent:thought",
                    {
                        "text": "The edit was not verified yet — asking for a check before the answer.",
                        "iteration": iteration,
                    },
                )
                live.append({"role": "assistant", "content": response})
                live.append({"role": "user", "content": VERIFY_AFTER_EDIT_PROMPT})
                _checkpoint(iteration + 1)
                continue
            if (
                work_tool_calls == 0
                and work_nudges < 1
                and _task_needs_tools(str(sub_task.get("task", "")), has_work_tools)
            ):
                work_nudges += 1
                _emit_event(
                    event_cb,
                    "agent:thought",
                    {
                        "text": "No work tool used yet — asking for the actual task before the answer.",
                        "iteration": iteration,
                    },
                )
                live.append({"role": "assistant", "content": response})
                live.append(
                    {
                        "role": "user",
                        "content": (
                            "You have only updated the checklist or talked about the work. "
                            "Use the appropriate work tool (search, read, edit, run, …) to "
                            "actually complete the task before giving FINAL_ANSWER."
                        ),
                    }
                )
                _checkpoint(iteration + 1)
                continue
            open_items = [item for item in get_todo_items() if item.get("status") != "completed"]
            if open_items and todo_nudges < 1:
                # The model tried to finish with an unfinished checklist. Ask
                # once for either completion or an explicit scope change so
                # "todo" cannot silently become decoration.
                todo_nudges += 1
                labels = ", ".join(str(item.get("label", "")) for item in open_items[:5])
                _emit_event(
                    event_cb,
                    "agent:thought",
                    {
                        "text": (
                            f"Checklist still has {len(open_items)} open item(s): {labels}. "
                            "Completing them before the final answer."
                        ),
                        "iteration": iteration,
                    },
                )
                live.append({"role": "assistant", "content": response})
                live.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your todo list still has {len(open_items)} incomplete item(s): "
                            f"{labels}. Finish them (or mark them completed if already done) "
                            "using todo_write, then provide FINAL_ANSWER."
                        ),
                    }
                )
                _checkpoint(iteration + 1)
                continue
            full_log.append(f"[Agent {agent_id}] Final answer ({len(final_answer)} chars)")
            _checkpoint(iteration + 1, status="completed", output=final_answer)
            return _finalize(final_answer)

        live.append({"role": "assistant", "content": response})
        live.append(
            {
                "role": "user",
                "content": (
                    WRAP_UP_PROMPT
                    if iteration == max_tool_iterations - 1
                    else "Continue working. Provide your FINAL_ANSWER when done."
                ),
            }
        )
        _checkpoint(iteration + 1)

    if _is_cancelled(run_control):
        return _cancelled_result(max_tool_iterations)

    # The tool budget was used up without a FINAL_ANSWER. Run one last call
    # (no tools) that forces the model to synthesize a best-effort answer, so
    # the user gets a real result instead of a generic timeout string.
    _emit_event(
        event_cb,
        "agent:thought",
        {
            "text": "Step limit reached — synthesizing final answer.",
            "iteration": max_tool_iterations,
        },
    )
    escalated = bool(escalation_model)
    if escalated and escalation_max_cost_usd > 0:
        from palimind.agents.pricing import estimate_cost_usd

        current_cost = estimate_cost_usd(usage)
        if current_cost >= escalation_max_cost_usd:
            _emit_event(
                event_cb,
                "agent:escalation",
                {
                    "from": worker_model,
                    "to": escalation_model,
                    "skipped": True,
                    "reason": (
                        f"cost ceiling reached (${current_cost:.4f} >= "
                        f"${escalation_max_cost_usd:.4f})"
                    ),
                    "iteration": max_tool_iterations,
                },
            )
            escalated = False
    if escalated:
        _emit_event(
            event_cb,
            "agent:escalation",
            {
                "from": worker_model,
                "to": escalation_model,
                "reason": "iteration budget exhausted without a final answer",
                "iteration": max_tool_iterations,
            },
        )
        _emit_event(
            event_cb,
            "agent:thought",
            {
                "text": (
                    f"Step limit reached — escalating from {worker_model} to "
                    f"{escalation_model} for the final synthesis."
                ),
                "iteration": max_tool_iterations,
            },
        )
    result = _call(
        None,
        extra_user=WRAP_UP_PROMPT,
        stream_mode="always" if token_stream else None,
        model_override=escalation_model if escalated else "",
        url_override=escalation_url if escalated else "",
    )
    response = result["content"] or ""
    _emit_event(
        event_cb,
        "agent:thought",
        {"text": response[:2000], "iteration": max_tool_iterations},
    )
    final_answer = _final_answer_candidate(response)
    if not final_answer:
        # A small model sometimes echoes a synthetic tool line instead of
        # answering. One clean retry usually recovers; the no-tools call cannot
        # actually execute anything, so this is safe.
        _emit_event(
            event_cb,
            "agent:thought",
            {
                "text": "Synthesis returned tool instructions — retrying as plain prose.",
                "iteration": max_tool_iterations,
            },
        )
        result = _call(
            None,
            extra_user=FINAL_SYNTHESIS_PROMPT,
            stream_mode="always" if token_stream else None,
            model_override=escalation_model if escalated else "",
            url_override=escalation_url if escalated else "",
        )
        response = result["content"] or ""
        final_answer = _final_answer_candidate(response)
    if final_answer:
        _checkpoint(max_tool_iterations, status="completed", output=final_answer)
        return _finalize(final_answer)
    # Last resort: the best substantive assistant prose already in the
    # transcript (never a synthetic tool line or a timeout marker).
    for message in reversed(live):
        if message.get("role") != "assistant":
            continue
        candidate = _final_answer_candidate(str(message.get("content") or ""))
        if candidate and len(candidate) >= 40:
            _checkpoint(max_tool_iterations, status="completed", output=candidate)
            return _finalize(candidate)
    _finish_usage()
    _checkpoint(
        max_tool_iterations, status="error", output="[Agent timed out - max iterations reached]"
    )
    return "[Agent timed out - max iterations reached]"


# ── helper ────────────────────────────────────────────────────────────────


def _tool_allowed(tool_name: str, sub_task: dict[str, Any], definition: Any | None = None) -> bool:
    """Enforce the per-run allowlist on both native and text-protocol calls.

    ``tool_pack="auto"`` keeps the legacy behaviour: any tier-appropriate tool
    may run even if it was not explicitly listed, so existing agents do not
    regress. Explicit packs and explicit tool lists are honoured strictly.
    """
    tools = sub_task.get("tools")
    if not tools:
        return True
    if tool_name in tools:
        return True
    if tool_name in {"ask_agent", "post_to_team", "read_team_notes", "tool_search", "todo_write"}:
        return True
    if definition is not None and str(getattr(definition, "tool_pack", "auto")) == "auto":
        return True
    return False


def _is_parallel_safe(
    tool_name: str,
    sub_task: dict[str, Any],
    definition: Any | None = None,
) -> bool:
    """True when a tool call may run concurrently with other read-only calls.

    Only registered, tier-1, approval-free, explicitly ``parallel_safe`` tools
    qualify. Writes, shell, browser mutations and anything that needs human
    approval always stay serial so they cannot race each other.
    """
    entry = TOOL_REGISTRY.get(tool_name)
    if not entry:
        return False
    if not bool(entry.get("parallel_safe")):
        return False
    meta = entry.get("meta") or {}
    if bool(meta.get("requires_approval")):
        return False
    if _tool_tier(tool_name) > 1:
        return False
    if not _tool_allowed(tool_name, sub_task, definition):
        return False
    return True


def _execute_tool_batch(
    agent_id: int,
    calls: list[dict[str, Any]],
    sub_task: dict[str, Any],
    on_step: Callable[[str], None] | None,
    full_log: list[str],
    *,
    definition: Any | None = None,
    approval_provider: Callable[[dict], dict] | None = None,
    response: str = "",
    event_cb: Callable[[str, dict], Any] | None = None,
    run_control: Any | None = None,
    read_files: set[str] | None = None,
) -> list[tuple[dict[str, Any], str]]:
    """Execute a model's tool calls, parallelising the safe read-only ones.

    Results are returned in the model's original call order, regardless of the
    order in which parallel calls finish, so the follow-up transcript is stable.
    """
    if not calls:
        return []

    parallel: list[int] = []
    serial: list[int] = []
    for idx, tc in enumerate(calls):
        name = str(tc.get("name") or "")
        if _is_parallel_safe(name, sub_task, definition):
            parallel.append(idx)
        else:
            serial.append(idx)

    results: list[str | None] = [None] * len(calls)

    def _run_one(index: int) -> str:
        tc = calls[index]
        if _is_cancelled(run_control):
            return "Access denied: the run was cancelled."
        return _execute_tool(
            agent_id,
            str(tc.get("name") or ""),
            {k: v for k, v in (tc.get("arguments") or {}).items()},
            sub_task,
            on_step,
            full_log,
            definition=definition,
            approval_provider=approval_provider,
            response=response,
            event_cb=event_cb,
            read_files=read_files,
        )

    if parallel:
        limit = max(1, min(int(MAX_PARALLEL_TOOLS or 4), len(parallel)))
        with ThreadPoolExecutor(max_workers=limit, thread_name_prefix="palimind-tool") as pool:
            futures = {
                pool.submit(contextvars.copy_context().run, _run_one, idx): idx for idx in parallel
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:  # noqa: BLE001 - one tool must not kill the batch
                    results[idx] = f"Tool error: {exc}"

    for idx in serial:
        try:
            results[idx] = _run_one(idx)
        except Exception as exc:  # noqa: BLE001
            results[idx] = f"Tool error: {exc}"

    out: list[tuple[dict[str, Any], str]] = []
    for i, call in enumerate(calls):
        value = results[i]
        out.append((call, value if value is not None else "Tool error: no result"))
    return out


def _execute_tool(
    agent_id: int,
    tool_name: str,
    tool_args: dict[str, Any],
    sub_task: dict[str, Any],
    on_step: Callable[[str], None] | None,
    full_log: list[str],
    *,
    definition: Any | None = None,
    approval_provider: Callable[[dict], dict] | None = None,
    response: str = "",
    event_cb: Callable[[str, dict], Any] | None = None,
    read_files: set[str] | None = None,
) -> str:
    if on_step:
        if tool_name == "web_search":
            q = str(tool_args.get("query", sub_task.get("task", "")))
            on_step(f"Searching web: '{q[:60]}'")
        else:
            on_step(f"Tool: {tool_name}")

    _emit_event(event_cb, "agent:tool_call", {"tool": tool_name, "args": tool_args})

    if not _tool_allowed(tool_name, sub_task, definition):
        tool_result = f"Access denied: tool '{tool_name}' is not in this agent's tool allowlist."
        _emit_event(
            event_cb,
            "agent:tool_result",
            {"tool": tool_name, "result": tool_result[:600]},
        )
        return tool_result

    target_path = str(tool_args.get("path") or tool_args.get("file_path") or "")
    normalized_path = target_path.replace("\\", "/").lstrip("./")
    if (
        read_files is not None
        and tool_name in {"search_replace", "apply_patch"}
        and normalized_path
        and normalized_path not in read_files
    ):
        tool_result = (
            f"Access denied: read '{target_path}' before editing it. "
            "Call read_file first so the change is based on the current content."
        )
        _emit_event(
            event_cb,
            "agent:tool_result",
            {"tool": tool_name, "result": tool_result[:600]},
        )
        full_log.append(f"[Agent {agent_id}] Blocked unread edit of {target_path}")
        return tool_result

    denial = _gate_tool(
        tool_name,
        tool_args,
        definition=definition,
        approval_provider=approval_provider,
        response=response,
    )
    if denial:
        tool_result = denial
    else:
        tool_result = call_tool(tool_name, **tool_args)
    if (
        read_files is not None
        and tool_name == "read_file"
        and normalized_path
        and not str(tool_result).startswith(("Error", "Access denied"))
    ):
        read_files.add(normalized_path)

    _report_web_step(on_step, tool_name, tool_result)
    _emit_event(
        event_cb,
        "agent:tool_result",
        {"tool": tool_name, "result": str(tool_result)[:600]},
    )
    if tool_name == "todo_write" and not denial:
        # Surface the checklist as its own event so the UI can render live
        # progress instead of scraping the tool-output string. An empty list
        # is meaningful: it clears the checklist.
        _emit_event(event_cb, "agent:todo", {"items": get_todo_items()})

    full_log.append(f"[Agent {agent_id}] Called {tool_name}: {tool_args}")
    full_log.append(f"[Agent {agent_id}] Result: {tool_result[:200]}")
    return tool_result
