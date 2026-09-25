from __future__ import annotations

import time
from collections.abc import Callable
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
    call_tool,
)
from palimind.settings import (
    MOE_CONTEXT_BUDGET_TOKENS,
    MOE_MAX_AGENT_ITERATIONS,
    MOE_NUM_CTX,
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

# Hard cap on the size of a tool result fed back into the model context so a
# single huge result cannot blow up the window and stall the loop.
MAX_TOOL_RESULT_CHARS = 8000

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
}

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

        threshold = float(getattr(definition, "human_in_loop_threshold", 0.0) or 0.0)
        if approval_provider is not None and threshold > 0 and tool_name in RISKY_TOOLS:
            return _request_approval(tool_name, tool_args, approval_provider, response)
        return None

    # ── definition-less (MoE) runs ─────────────────────────────────────
    # Isolated compute stays allowed; file mutations and shell execution must
    # be explicitly approved, mirroring named-agent write_access/HITL.
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
    """
    del session_id  # correlation only; kept for interface compatibility

    _register_plugin_tools()

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
    native_tools = (
        ollama_tools_from_registry({name: TOOL_REGISTRY[name] for name in allowed_tools})
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

    base = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": build_agent_prompt(agent_id, sub_task, worker_model, briefing=briefing),
        },
    ]
    live: list[dict] = []
    working_notes: list[str] = []

    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}

    def _track(result: dict) -> None:
        u = result.get("usage") or {}
        usage["prompt_tokens"] += int(u.get("prompt_tokens", 0))
        usage["completion_tokens"] += int(u.get("completion_tokens", 0))

    def _call(
        tools: list[dict] | None,
        extra_user: str | None = None,
        stream_mode: str | None = None,
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

        if not (token_stream and stream_mode):
            result = llm_chat_safe(
                msgs,
                worker_model,
                ollama_url,
                tools=tools,
                error_prefix=f"[Agent {agent_id} error",
                temperature=temperature,
                num_ctx=MOE_NUM_CTX,
            )
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
                    worker_model,
                    ollama_url,
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
        result = llm_chat_safe(
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

    def _finalize(answer: str) -> str:
        """Optionally self-critique, then emit the final answer exactly once."""
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

    full_log: list[str] = []
    recent_tool_calls: list[str] = []
    for iteration in range(max_tool_iterations):
        result = _call(native_tools, stream_mode="detect" if token_stream else None)
        response = result["content"]
        _emit_event(
            event_cb, "agent:thought", {"text": (response or "")[:2000], "iteration": iteration}
        )

        # ── 1. Native tool calls (preferred) ──────────────────────────
        if result["tool_calls"]:
            for tc in result["tool_calls"]:
                tool_name = tc["name"]
                native_args = {k: v for k, v in (tc.get("arguments") or {}).items()}
                tool_result = _execute_tool(
                    agent_id,
                    tool_name,
                    native_args,
                    sub_task,
                    on_step,
                    full_log,
                    definition=definition,
                    approval_provider=approval_provider,
                    response=response,
                    event_cb=event_cb,
                )
                live.append(
                    {"role": "assistant", "content": response or f"[tool call: {tool_name}]"}
                )
                live.append(
                    {
                        "role": "user",
                        "content": (
                            f"Tool '{tool_name}' returned:\n{tool_result[:MAX_TOOL_RESULT_CHARS]}"
                        ),
                    }
                )
                recent_tool_calls.append(_tool_signature(tool_name, native_args))
            working_notes = _compact_context(live, working_notes, ctx_budget)
            if _is_looping(recent_tool_calls):
                _emit_event(
                    event_cb,
                    "agent:thought",
                    {"text": "Repeated tool call detected — wrapping up.", "iteration": iteration},
                )
                live.append({"role": "assistant", "content": response})
                live.append({"role": "user", "content": WRAP_UP_PROMPT})
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
            _emit_event(event_cb, "agent:tool_call", {"tool": tool_name, "args": tool_args})
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

            tool_msg = f"Tool '{tool_name}' returned:\n{tool_result[:MAX_TOOL_RESULT_CHARS]}"
            full_log.append(f"[Agent {agent_id}] Called {tool_name}: {tool_args}")
            full_log.append(f"[Agent {agent_id}] Result: {tool_result[:200]}")
            live.append({"role": "assistant", "content": response})
            live.append({"role": "user", "content": tool_msg})
            recent_tool_calls.append(_tool_signature(tool_name, tool_args))
            working_notes = _compact_context(live, working_notes, ctx_budget)
            if _is_looping(recent_tool_calls):
                _emit_event(
                    event_cb,
                    "agent:thought",
                    {"text": "Repeated tool call detected — wrapping up.", "iteration": iteration},
                )
                live.append({"role": "assistant", "content": response})
                live.append({"role": "user", "content": WRAP_UP_PROMPT})
            continue

        # ── 3. Final answer ───────────────────────────────────────────
        if "FINAL_ANSWER:" in response:
            final_answer = parse_agent_output(response)
            full_log.append(f"[Agent {agent_id}] Final answer ({len(final_answer)} chars)")
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
    result = _call(None, extra_user=WRAP_UP_PROMPT, stream_mode="always" if token_stream else None)
    response = result["content"] or ""
    _emit_event(
        event_cb,
        "agent:thought",
        {"text": response[:2000], "iteration": max_tool_iterations},
    )
    final_answer = parse_agent_output(response)
    if final_answer and ("FINAL_ANSWER:" in response or not final_answer.startswith("[Agent ")):
        return _finalize(final_answer)
    _finish_usage()
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
