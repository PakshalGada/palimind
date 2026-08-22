from __future__ import annotations

from typing import Any, Callable

from core.llm.mixture_of_expert.llm import llm_chat_safe, ollama_tools_from_registry
from core.llm.mixture_of_expert.planner import (
    build_agent_prompt,
    parse_agent_output,
    parse_tool_call,
)
from core.llm.mixture_of_expert.tools import (
    AVAILABLE_TOOLS_DESC,
    TOOL_REGISTRY,
    call_tool,
)


def _report_web_step(on_step: Callable[[str], None] | None, tool_name: str, tool_result: str) -> None:
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


# ── custom-agent (definition-based) support ───────────────────────────────

# Tools that mutate state and may require human-in-the-loop approval.
RISKY_TOOLS = {"write_file", "run_python"}


def _emit_event(event_cb: Callable[[str, dict], Any] | None, etype: str, payload: dict) -> None:
    """Best-effort structured event emission (SSE reasoning chain)."""
    if event_cb is None:
        return
    try:
        event_cb(etype, payload)
    except Exception as e:
        print(f"[Agent] event emit failed ({etype}): {e}")


def _gate_tool(
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    definition: Any | None = None,
    approval_provider: Callable[[dict], dict] | None = None,
    response: str = "",
) -> str | None:
    """Return a denial-reason string if the tool call must be blocked.

    Enforces the definition's write/shell access flags unconditionally and
    consults ``approval_provider`` for risky tools when a HITL threshold is
    configured. Returns None when the call may proceed.
    """
    if definition is not None:
        if tool_name == "write_file" and not getattr(definition, "write_access", True):
            return f"Access denied: this agent does not have write_access ('{tool_name}' blocked)"
        if tool_name == "run_python" and not getattr(definition, "shell_access", True):
            return f"Access denied: this agent does not have shell_access ('{tool_name}' blocked)"

        threshold = float(getattr(definition, "human_in_loop_threshold", 0.0) or 0.0)
        if approval_provider is not None and threshold > 0 and tool_name in RISKY_TOOLS:
            try:
                result = approval_provider(
                    {
                        "tool": tool_name,
                        "args": tool_args,
                        "confidence": 0.0,
                        "threshold": threshold,
                        "reasoning": (response or "")[:300],
                    }
                )
                approved = bool((result or {}).get("approved"))
                correction = (result or {}).get("correction", "")
                if not approved:
                    reason = "the human reviewer rejected this action"
                    if correction:
                        reason += f' with feedback: "{correction}"'
                    return f"Human reviewer rejected '{tool_name}': {reason}"
            except Exception as e:
                return f"Approval flow error for '{tool_name}': {e}"
    return None


def run_agent(
    agent_id: int,
    sub_task: dict[str, Any],
    worker_model: str,
    ollama_url: str,
    max_tool_iterations: int = 8,
    on_step: Callable[[str], None] | None = None,
    definition: Any | None = None,
    extra_system_prompt: str = "",
    event_cb: Callable[[str, dict], Any] | None = None,
    approval_provider: Callable[[dict], dict] | None = None,
    session_id: str = "",
) -> str:
    """Run one agent loop.

    The first six parameters are the original MoE worker interface. The
    keyword parameters support definition-driven custom agents
    (core.agents.runtime.run_with_definition):

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
    """
    del session_id  # correlation only; kept for interface compatibility

    allowed_tools = [t for t in sub_task.get("tools", []) if t in TOOL_REGISTRY]
    native_tools = (
        ollama_tools_from_registry(
            {name: TOOL_REGISTRY[name] for name in allowed_tools}
        )
        if allowed_tools
        else None
    )

    temperature = getattr(definition, "temperature", None) if definition else None

    system_prompt = f"""You are Agent {agent_id}, an expert in a Mixture-of-Experts system.
You execute assigned sub-tasks using available tools.

Available tools:
{AVAILABLE_TOOLS_DESC if not allowed_tools else chr(10).join(f"- {t}: {TOOL_REGISTRY[t]['description']}" for t in allowed_tools)}

When native tool calls are available, call tools directly.

Otherwise, to use a tool, respond with:
  TOOL: tool_name
  ARGS: key1=value1, key2=value2
(ARGS may also be a JSON object on one line.)

When your task is complete, respond with:
  FINAL_ANSWER:
  <your final answer>

Be concise and effective."""

    if extra_system_prompt:
        system_prompt = f"{system_prompt}\n\n{extra_system_prompt}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": build_agent_prompt(agent_id, sub_task, worker_model)},
    ]

    full_log: list[str] = []
    for iteration in range(max_tool_iterations):
        result = llm_chat_safe(
            messages,
            worker_model,
            ollama_url,
            tools=native_tools,
            error_prefix=f"[Agent {agent_id} error",
            temperature=temperature,
        )
        response = result["content"]
        _emit_event(
            event_cb, "agent:thought", {"text": (response or "")[:400], "iteration": iteration}
        )

        # ── 1. Native tool calls (preferred) ──────────────────────────
        if result["tool_calls"]:
            for tc in result["tool_calls"]:
                tool_name = tc["name"]
                tool_args = {k: v for k, v in (tc.get("arguments") or {}).items()}
                tool_result = _execute_tool(
                    agent_id, tool_name, tool_args, sub_task, on_step, full_log,
                    definition=definition,
                    approval_provider=approval_provider,
                    response=response,
                    event_cb=event_cb,
                )
                messages.append({"role": "assistant", "content": response or f"[tool call: {tool_name}]"})
                messages.append(
                    {
                        "role": "user",
                        "content": f"Tool '{tool_name}' returned:\n{tool_result}",
                    }
                )
            continue

        # ── 2. Text-protocol tool call (fallback) ─────────────────────
        tool_name, tool_args = parse_tool_call(response)
        if tool_name:
            if on_step:
                if tool_name == "web_search":
                    q = (tool_args or {}).get("query", sub_task.get("task", ""))
                    on_step(f"Searching web: '{q[:60]}'")
                else:
                    on_step(f"Tool: {tool_name}")

            denial = _gate_tool(
                tool_name,
                tool_args or {},
                definition=definition,
                approval_provider=approval_provider,
                response=response,
            )
            _emit_event(
                event_cb, "agent:tool_call", {"tool": tool_name, "args": tool_args}
            )
            if denial:
                tool_result = denial
            else:
                tool_result = call_tool(tool_name, **(tool_args or {}))
            _report_web_step(on_step, tool_name, tool_result)
            _emit_event(
                event_cb,
                "agent:tool_result",
                {"tool": tool_name, "result": str(tool_result)[:600]},
            )

            tool_msg = f"Tool '{tool_name}' returned:\n{tool_result}"
            full_log.append(f"[Agent {agent_id}] Called {tool_name}: {tool_args}")
            full_log.append(f"[Agent {agent_id}] Result: {tool_result[:200]}")
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": tool_msg})
            continue

        # ── 3. Proactive fallback: research agents search on turn 0 ───
        if "web_search" in allowed_tools and iteration == 0 and "FINAL_ANSWER:" not in response:
            query = sub_task.get("task", "")[:100] or "latest information"
            if on_step:
                on_step(f"Searching web: '{query[:60]}'")

            tool_result = call_tool("web_search", query=query, max_results=3)
            _report_web_step(on_step, "web_search", tool_result)

            tool_msg = f"Tool 'web_search' auto-executed for research returned:\n{tool_result}"
            full_log.append(f"[Agent {agent_id}] Auto-executed web_search: {query}")
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": tool_msg})
            continue

        # ── 4. Final answer ───────────────────────────────────────────
        if "FINAL_ANSWER:" in response:
            final_answer = parse_agent_output(response)
            full_log.append(f"[Agent {agent_id}] Final answer ({len(final_answer)} chars)")
            return final_answer

        messages.append({"role": "assistant", "content": response})
        messages.append(
            {"role": "user", "content": "Continue working. Provide your FINAL_ANSWER when done."}
        )

    return "[Agent timed out - max iterations reached]"


# ── helper ────────────────────────────────────────────────────────────────


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
) -> str:
    if on_step:
        if tool_name == "web_search":
            q = str(tool_args.get("query", sub_task.get("task", "")))
            on_step(f"Searching web: '{q[:60]}'")
        else:
            on_step(f"Tool: {tool_name}")

    _emit_event(event_cb, "agent:tool_call", {"tool": tool_name, "args": tool_args})

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

    _report_web_step(on_step, tool_name, tool_result)
    _emit_event(
        event_cb,
        "agent:tool_result",
        {"tool": tool_name, "result": str(tool_result)[:600]},
    )

    full_log.append(f"[Agent {agent_id}] Called {tool_name}: {tool_args}")
    full_log.append(f"[Agent {agent_id}] Result: {tool_result[:200]}")
    return tool_result
