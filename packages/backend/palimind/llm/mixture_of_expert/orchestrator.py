from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from palimind.llm.mixture_of_expert.agents import run_agent
from palimind.llm.mixture_of_expert.llm import llm_chat_safe
from palimind.llm.mixture_of_expert.planner import (
    build_planner_prompt,
    build_synthesis_prompt,
    build_verify_prompt,
    parse_plan,
)
from palimind.llm.mixture_of_expert.tools import set_tool_context
from palimind.settings import (
    MOE_MAX_CONCURRENCY,
    MOE_NUM_CTX,
    MOE_VERIFY,
)

# ── query routing ─────────────────────────────────────────────────────────

_WEB_HINTS = re.compile(
    r"\b(latest|news|current|today|yesterday|breaking|price of|stock|weather|"
    r"who won|release|update|2024|2025|2026|recent|happened)\b",
    re.IGNORECASE,
)
_DOC_HINTS = re.compile(
    r"\b(my (documents?|docs?|files?|notes?|workspace|field)|the documents?|"
    r"in my (index|library)|which file)\b",
    re.IGNORECASE,
)
_CODE_HINTS = re.compile(
    r"\b(code|script|function|debug|python|implement|program|regex|algorithm|"
    r"refactor|write a (class|module|cli))\b",
    re.IGNORECASE,
)
_SIMPLE_HINTS = re.compile(
    r"^(hi|hello|hey|thanks|thank you|ok|okay|great|cool)[\s!.?]*$", re.IGNORECASE
)


def heuristic_route(query: str) -> dict[str, Any]:
    """Fast keyword-based routing used as fallback / prior for the LLM router."""
    return {
        "needs_web": bool(_WEB_HINTS.search(query)),
        "needs_docs": bool(_DOC_HINTS.search(query)),
        "needs_code": bool(_CODE_HINTS.search(query)),
        "needs_memory": False,
        "simple": bool(_SIMPLE_HINTS.match(query.strip())),
    }


def route_query(
    query: str,
    router_model: str,
    ollama_url: str,
    usage_cb: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """Classify the query to guide planning. LLM-based with heuristic fallback."""
    prior = heuristic_route(query)
    prompt = (
        "Classify this user query for an AI agent system. Respond with ONLY a JSON "
        "object with these boolean fields: needs_web (live/current internet info "
        "required), needs_docs (about the user's own indexed documents), needs_code "
        "(coding/execution required), needs_memory (past conversations referenced), "
        'simple (casual/trivial query).\n\nQuery: "' + query.replace('"', "'") + '"'
    )
    result = llm_chat_safe(
        [{"role": "user", "content": prompt}],
        router_model,
        ollama_url,
        format="json",
        temperature=0.0,
        num_predict=80,
        read_timeout=30.0,
        num_ctx=MOE_NUM_CTX,
        error_prefix="[router error",
    )
    if usage_cb is not None:
        usage_cb(result.get("usage") or {})
    try:
        parsed = json.loads(result["content"])
    except (json.JSONDecodeError, TypeError):
        return prior

    route = dict(prior)
    for key in route:
        if key in parsed:
            route[key] = bool(parsed[key])
    return route


def _is_trivial_query(query: str) -> bool:
    """High-confidence triviality check that skips the router LLM entirely.

    Greetings, and short queries with no web/docs/code hints, are almost
    always general-knowledge questions answerable by a single direct
    response — running the full multi-agent pipeline on them wastes minutes.
    """
    q = query.strip()
    if not q:
        return True
    if _SIMPLE_HINTS.match(q):
        return True
    if len(q) <= 60 and not (_WEB_HINTS.search(q) or _DOC_HINTS.search(q) or _CODE_HINTS.search(q)):
        return True
    return False


def _is_simple_route(route: dict[str, Any]) -> bool:
    """True when the query can take the single-agent direct path.

    A route flagged simple that ALSO needs web/docs/code/memory is treated
    as non-simple — the tools matter more than the simplicity.
    """
    if not route.get("simple"):
        return False
    return not any(route.get(k) for k in ("needs_web", "needs_docs", "needs_code", "needs_memory"))


def _agent_count_for_route(route: dict[str, Any], requested: int) -> int:
    if _is_simple_route(route):
        return 1
    if route.get("simple"):
        return max(1, min(requested, 2))
    return requested


def _default_plan(query: str, route: dict[str, Any], num_workers: int) -> list[dict[str, Any]]:
    """Fallback plan when the orchestrator LLM fails to produce valid JSON."""
    plan: list[dict[str, Any]] = []
    if route.get("needs_web"):
        plan.append(
            {
                "agent_id": 1,
                "label": "Researcher (Web Search)",
                "task": f"Search the web for up-to-date information and facts about: {query}",
                "tools": ["web_search", "fetch_url"],
                "context": query,
            }
        )
    plan.append(
        {
            "agent_id": len(plan) + 1,
            "label": "Analyst",
            "task": f"Analyze context and requirements for: {query}",
            "tools": ["document_search"] if route.get("needs_docs") else [],
            "context": query,
        }
    )
    if len(plan) < num_workers and route.get("needs_code"):
        plan.append(
            {
                "agent_id": len(plan) + 1,
                "label": "Engineer",
                "task": f"Formulate solution or code logic for: {query}",
                "tools": ["run_python", "write_file"],
                "context": query,
            }
        )
    if len(plan) < num_workers:
        plan.append(
            {
                "agent_id": len(plan) + 1,
                "label": "Reviewer & Synthesizer",
                "task": f"Review and verify output accuracy for: {query}",
                "tools": [],
                "context": query,
            }
        )
    return plan[:num_workers]


def _model_is_loaded(ollama_url: str, model: str) -> bool:
    """Return True when *model* is currently resident in Ollama (/api/ps)."""
    import httpx

    try:
        resp = httpx.get(f"{ollama_url.rstrip('/')}/api/ps", timeout=5.0)
        if resp.status_code != 200:
            return False
        data = resp.json()
        return any(m.get("model") == model for m in data.get("models", []))
    except Exception:
        return False


def _max_concurrency(num_workers: int, ollama_url: str = "", worker_model: str = "") -> int:
    """Clamp parallel agent execution.

    Precedence:
    1. Explicit PALIMIND_MOE_MAX_CONCURRENCY override.
    2. If all workers share the same model that is already loaded in Ollama,
       cap at 2 — concurrent requests on one model just queue, but a second
       slot lets one agent's slow tool I/O overlap another's LLM call.
    3. Fall back to a system-RAM heuristic.
    """
    configured = MOE_MAX_CONCURRENCY
    if configured > 0:
        return max(1, min(configured, num_workers))
    if ollama_url and worker_model and _model_is_loaded(ollama_url, worker_model):
        return max(1, min(2, num_workers))
    try:
        import psutil

        ram_gb = psutil.virtual_memory().total / (1024**3)
        if ram_gb < 8:
            return 1
        if ram_gb < 16:
            return 2
    except Exception:
        pass
    return min(num_workers, 4)


def _needs_refinement(critique: dict[str, Any]) -> bool:
    if not critique:
        return False
    if critique.get("answers_query") is False:
        return True
    for key in ("missing_scope", "missing_facts", "conflicts"):
        if str(critique.get(key) or "").strip():
            return True
    return False


def _format_verify_feedback(critique: dict[str, Any]) -> str:
    lines = []
    for key, label in (
        ("missing_scope", "Did not fully answer the query"),
        ("missing_facts", "Missing important facts"),
        ("conflicts", "Conflicting or unsupported claims"),
        ("suggestions", "Suggestions"),
    ):
        value = str(critique.get(key) or "").strip()
        if value:
            lines.append(f"- {label}: {value}")
    return (
        "\n".join(lines)
        if lines
        else "Reviewer found no specific issues; make the answer more precise."
    )


# ── pipeline ──────────────────────────────────────────────────────────────


async def run_moe_pipeline(
    user_query: str,
    ollama_url: str,
    orchestrator_model: str,
    worker_model: str,
    num_workers: int = 4,
    on_progress: Callable[[dict], Awaitable[None]] | None = None,
    short_term: list[dict] | None = None,
    mid_term_summary: str | None = None,
    long_term_episodes: list[dict] | None = None,
    root: Path | None = None,
    worker_url: str | None = None,
) -> dict[str, Any]:
    from palimind.memory.hierarchical import format_hierarchical_memory_context

    memory_ctx = format_hierarchical_memory_context(mid_term_summary, long_term_episodes or [])

    async def emit(event: dict):
        if on_progress:
            await on_progress(event)

    # Expose workspace context to agent tools (sandboxed file/doc/memory access)
    light_model = ""
    if root is not None:
        try:
            from palimind.config import load_config

            cfg = load_config(root)
            light_model = cfg.get("light_model", "") or cfg.get("chat_model", "")
        except Exception:
            light_model = ""
    set_tool_context(root, worker_url or ollama_url, worker_model, light_model)

    # ── usage telemetry / stage timings ──────────────────────────────────
    usage: dict[str, dict] = {}
    timings: dict[str, float] = {}
    t_start = time.monotonic()

    def _capture(stage: str, result: dict) -> None:
        u = result.get("usage") or {}
        if u:
            usage[stage] = u

    # ── Route ────────────────────────────────────────────────────────────
    await emit({"type": "planning", "text": "Routing query..."})
    t = time.monotonic()
    if _is_trivial_query(user_query):
        # High-confidence trivial query: skip the router LLM call entirely.
        route = heuristic_route(user_query)
        route["simple"] = True
    else:
        route = await asyncio.to_thread(
            route_query,
            user_query,
            light_model or orchestrator_model,  # classification → cheap model
            ollama_url,
            lambda u: _capture("route", {"usage": u}),
        )
    timings["route"] = time.monotonic() - t
    num_workers = _agent_count_for_route(route, num_workers)
    simple_route = _is_simple_route(route)

    # ── Shared web briefing (one search, injected into every agent) ──────
    briefing = ""
    if route.get("needs_web"):
        from palimind.core.web_search import perform_web_search

        await emit({"type": "planning", "text": "Gathering shared web briefing..."})
        t = time.monotonic()
        briefing = await asyncio.to_thread(
            perform_web_search, user_query, max_results=4, fetch_content=True
        )
        timings["briefing"] = time.monotonic() - t

    # ── Plan ─────────────────────────────────────────────────────────────
    if simple_route:
        # Fast path: a simple general-knowledge question gets ONE direct
        # responder with no tools — no planner LLM call, no multi-agent.
        await emit({"type": "planning", "text": "Simple query — direct response path..."})
        plan: list[dict[str, Any]] = [
            {
                "agent_id": 1,
                "label": "Direct Responder",
                "task": f"Answer the user's question directly and concisely: {user_query}",
                "tools": [],
                "context": "",
            }
        ]
    else:
        await emit({"type": "planning", "text": "Planning with orchestrator model..."})
        t = time.monotonic()
        plan_prompt = build_planner_prompt(
            user_query, num_workers, memory_context=memory_ctx, route_hints=route
        )
        plan_result = await asyncio.to_thread(
            llm_chat_safe,
            [{"role": "user", "content": plan_prompt}],
            orchestrator_model,
            ollama_url,
            format="json",
            temperature=0.2,
            read_timeout=600.0,
            num_ctx=MOE_NUM_CTX,
            error_prefix="[orchestrator error",
        )
        _capture("planner", plan_result)
        timings["plan"] = time.monotonic() - t
        plan = parse_plan(plan_result["content"], num_workers)

        if not plan:
            plan = _default_plan(user_query, route, num_workers)

        # Apply routing hints: ensure the web researcher exists only when needed
        has_web_agent = any("web_search" in a.get("tools", []) for a in plan)
        if route.get("needs_web") and not has_web_agent:
            researcher = {
                "agent_id": 0,
                "label": "Researcher (Web Search)",
                "task": f"Search the web for up-to-date information and facts about: {user_query}",
                "tools": ["web_search", "fetch_url"],
                "context": user_query,
            }
            if len(plan) < num_workers:
                researcher["agent_id"] = len(plan) + 1
                plan.append(researcher)
            else:
                plan[-1] = researcher
        if route.get("needs_docs"):
            for a in plan:
                if not a.get("tools"):
                    a["tools"] = ["document_search"]
                    break

    # ── Execute agents (concurrency-limited) ─────────────────────────────
    loop = asyncio.get_running_loop()
    semaphore = asyncio.Semaphore(
        _max_concurrency(num_workers, worker_url or ollama_url, worker_model)
    )

    async def run_single_agent(sub_task: dict, idx: int) -> dict:
        agent_id = sub_task.get("agent_id", idx + 1)
        label = sub_task.get("label") or f"Agent {agent_id}"
        task_desc = sub_task.get("task", "")[:80]

        await emit(
            {
                "type": "agent_start",
                "agent_id": agent_id,
                "label": label,
                "task": task_desc,
            }
        )

        def on_step_callback(step_text: str):
            asyncio.run_coroutine_threadsafe(
                emit(
                    {
                        "type": "agent_step",
                        "agent_id": agent_id,
                        "text": step_text,
                    }
                ),
                loop,
            )

        agent_usage: dict[str, int] = {}

        async with semaphore:
            output = await asyncio.to_thread(
                run_agent,
                agent_id,
                sub_task,
                worker_model,
                worker_url or ollama_url,
                None,  # adaptive per-agent budget
                on_step_callback,
                briefing=briefing,
                usage_cb=agent_usage.update,
            )
        if agent_usage:
            usage[f"agent_{agent_id}"] = dict(agent_usage)

        await emit(
            {
                "type": "agent_complete",
                "agent_id": agent_id,
                "label": label,
            }
        )
        return {
            "agent_id": agent_id,
            "label": label,
            "task": sub_task.get("task", ""),
            "output": output,
        }

    tasks = [run_single_agent(sub_task, i) for i, sub_task in enumerate(plan[:num_workers])]
    t = time.monotonic()
    agent_outputs = list(await asyncio.gather(*tasks))
    timings["agents"] = time.monotonic() - t

    # ── Synthesize ───────────────────────────────────────────────────────
    # Direct path: a single tool-less agent already answered the query —
    # re-synthesizing its output through another LLM call is pure latency.
    direct_answer = simple_route and len(agent_outputs) == 1
    if direct_answer:
        synthesis = agent_outputs[0].get("output", "") or "No output produced."
    else:
        await emit({"type": "synthesizing", "text": "Synthesizing results..."})
        t = time.monotonic()
        synthesis_prompt = build_synthesis_prompt(
            user_query, agent_outputs, memory_context=memory_ctx
        )
        synthesis_result = await asyncio.to_thread(
            llm_chat_safe,
            [{"role": "user", "content": synthesis_prompt}],
            orchestrator_model,
            ollama_url,
            read_timeout=600.0,
            num_ctx=MOE_NUM_CTX,
            error_prefix="[synthesis error",
        )
        _capture("synthesis", synthesis_result)
        timings["synthesis"] = time.monotonic() - t
        synthesis = synthesis_result["content"]

    # ── Verify / refine (one bounded re-synthesis pass) ──────────────────
    if MOE_VERIFY and synthesis and not direct_answer:
        await emit({"type": "verifying", "text": "Verifying synthesis quality..."})
        verify_model = light_model or orchestrator_model
        verify_prompt = build_verify_prompt(user_query, synthesis, agent_outputs)
        t = time.monotonic()
        verify_result = await asyncio.to_thread(
            llm_chat_safe,
            [{"role": "user", "content": verify_prompt}],
            verify_model,
            ollama_url,
            format="json",
            temperature=0.0,
            num_predict=400,
            read_timeout=60.0,
            num_ctx=MOE_NUM_CTX,
            error_prefix="[verify error",
        )
        _capture("verify", verify_result)
        timings["verify"] = time.monotonic() - t
        try:
            critique = json.loads(verify_result["content"])
        except (json.JSONDecodeError, TypeError):
            critique = {}
        if _needs_refinement(critique):
            feedback = _format_verify_feedback(critique)
            await emit({"type": "verifying", "text": "Refining synthesis after review..."})
            refined_prompt = (
                f"{synthesis_prompt}\n\nREVIEW FEEDBACK (address these issues and "
                f"return the improved final answer):\n{feedback}"
            )
            refined_result = await asyncio.to_thread(
                llm_chat_safe,
                [{"role": "user", "content": refined_prompt}],
                orchestrator_model,
                ollama_url,
                read_timeout=600.0,
                num_ctx=MOE_NUM_CTX,
                error_prefix="[synthesis error",
            )
            _capture("synthesis_refine", refined_result)
            if refined_result["content"]:
                synthesis = refined_result["content"]

    timings["total"] = time.monotonic() - t_start
    await emit({"type": "complete"})
    return {
        "plan": plan,
        "outputs": agent_outputs,
        "synthesis": synthesis,
        "route": route,
        "usage": usage,
        "timings": timings,
    }
