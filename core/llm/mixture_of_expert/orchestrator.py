from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from core.llm.mixture_of_expert.agents import run_agent
from core.llm.mixture_of_expert.llm import llm_chat_safe
from core.llm.mixture_of_expert.planner import (
    build_planner_prompt,
    build_synthesis_prompt,
    parse_plan,
)
from core.llm.mixture_of_expert.tools import set_tool_context

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
_SIMPLE_HINTS = re.compile(r"^(hi|hello|hey|thanks|thank you|ok|okay|great|cool)[\s!.?]*$", re.IGNORECASE)


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
) -> dict[str, Any]:
    """Classify the query to guide planning. LLM-based with heuristic fallback."""
    prior = heuristic_route(query)
    prompt = (
        "Classify this user query for an AI agent system. Respond with ONLY a JSON "
        'object with these boolean fields: needs_web (live/current internet info '
        "required), needs_docs (about the user's own indexed documents), needs_code "
        "(coding/execution required), needs_memory (past conversations referenced), "
        'simple (casual/trivial query).\n\nQuery: "'
        + query.replace('"', "'")
        + '"'
    )
    result = llm_chat_safe(
        [{"role": "user", "content": prompt}],
        router_model,
        ollama_url,
        format="json",
        temperature=0.0,
        num_predict=80,
        read_timeout=30.0,
        error_prefix="[router error",
    )
    try:
        parsed = json.loads(result["content"])
    except (json.JSONDecodeError, TypeError):
        return prior

    route = dict(prior)
    for key in route:
        if key in parsed:
            route[key] = bool(parsed[key])
    return route


def _agent_count_for_route(route: dict[str, Any], requested: int) -> int:
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
            "tools": ["document_search"] if route.get("needs_docs") else ["list_files"],
            "context": query,
        }
    )
    if len(plan) < num_workers and (route.get("needs_code") or num_workers >= 3):
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


def _max_concurrency(num_workers: int) -> int:
    """Clamp parallel agent execution based on available system RAM."""
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
) -> dict[str, Any]:
    from core.memory import format_hierarchical_memory_context

    memory_ctx = format_hierarchical_memory_context(mid_term_summary, long_term_episodes or [])

    async def emit(event: dict):
        if on_progress:
            await on_progress(event)

    # Expose workspace context to agent tools (sandboxed file/doc/memory access)
    light_model = ""
    if root is not None:
        try:
            from core.config import load_config

            cfg = load_config(root)
            light_model = cfg.get("light_model", "") or cfg.get("chat_model", "")
        except Exception:
            light_model = ""
    set_tool_context(root, ollama_url, worker_model, light_model)

    # ── Route ────────────────────────────────────────────────────────────
    await emit({"type": "planning", "text": "Routing query..."})
    route = await asyncio.to_thread(route_query, user_query, orchestrator_model, ollama_url)
    num_workers = _agent_count_for_route(route, num_workers)

    # ── Plan ─────────────────────────────────────────────────────────────
    await emit({"type": "planning", "text": "Planning with orchestrator model..."})
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
        error_prefix="[orchestrator error",
    )
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
    semaphore = asyncio.Semaphore(_max_concurrency(num_workers))

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

        async with semaphore:
            output = await asyncio.to_thread(
                run_agent,
                agent_id,
                sub_task,
                worker_model,
                ollama_url,
                8,
                on_step_callback,
            )

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
    agent_outputs = list(await asyncio.gather(*tasks))

    # ── Synthesize ───────────────────────────────────────────────────────
    await emit({"type": "synthesizing", "text": "Synthesizing results..."})
    synthesis_prompt = build_synthesis_prompt(user_query, agent_outputs, memory_context=memory_ctx)
    synthesis_result = await asyncio.to_thread(
        llm_chat_safe,
        [{"role": "user", "content": synthesis_prompt}],
        orchestrator_model,
        ollama_url,
        read_timeout=600.0,
        error_prefix="[synthesis error",
    )
    synthesis = synthesis_result["content"]

    await emit({"type": "complete"})
    return {
        "plan": plan,
        "outputs": agent_outputs,
        "synthesis": synthesis,
        "route": route,
    }
