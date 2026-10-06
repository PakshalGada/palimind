"""Multi-agent orchestration: fan-out, blackboard, synthesis, arena.

Phase 4.2 brings Grok-Heavy-style orchestration to PaliMind. A complex task is
decomposed into sub-tasks, N agents run them (in parallel, bounded by a
semaphore), their findings are collected on a shared **blackboard**, and a
**synthesis** pass produces the final answer. When agents disagree a
**conflict-resolution** pass is run first.

Two modes are supported:

* ``fan_out`` — decompose + parallel + synthesise (the default).
* ``arena``   — run the *same* task N times and have a judge pick the winner
  (tournament-style evaluation).

The module mirrors the existing Mixture-of-Experts orchestrator's concurrency
and tool-context handling so it composes with the rest of the runtime. Every
stage emits structured events (``orchestrator:*``) for the agent activity graph.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from palimind.llm.mixture_of_expert.agents import run_agent
from palimind.llm.mixture_of_expert.llm import llm_chat_safe
from palimind.llm.mixture_of_expert.planner import (
    build_planner_prompt,
    build_synthesis_prompt,
    parse_plan,
)
from palimind.llm.mixture_of_expert.tools import set_tool_context
from palimind.settings import (
    MOE_NUM_CTX,
    ORCHESTRATOR_CONFLICT_RESOLUTION,
    ORCHESTRATOR_DEFAULT_AGENTS,
    ORCHESTRATOR_MAX_AGENTS,
    ORCHESTRATOR_MAX_CONCURRENCY,
)

ORCHESTRATION_MODES = ("fan_out", "arena")


# ── shared blackboard ─────────────────────────────────────────────────────


class Blackboard:
    """Thread-safe shared scratchpad for orchestrated agents."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def post(
        self,
        agent_id: Any,
        label: str,
        content: str,
        *,
        task: str = "",
        kind: str = "finding",
    ) -> dict[str, Any]:
        entry = {
            "agent_id": agent_id,
            "label": label,
            "task": task,
            "content": str(content),
            "kind": kind,
            "ts": time.time(),
        }
        with self._lock:
            self._entries.append(entry)
        return entry

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._entries)

    def render(self, limit_chars: int = 12_000) -> str:
        """Render the blackboard as an injectable context block."""
        parts: list[str] = []
        for e in self.entries():
            parts.append(
                f"### {e['label']} (agent {e['agent_id']})\n"
                f"Task: {e.get('task', '')[:200]}\n{e.get('content', '')[:4000]}"
            )
        text = "\n\n".join(parts)
        return text[:limit_chars]


# ── planning ──────────────────────────────────────────────────────────────


def clamp_agent_count(n: int | None) -> int:
    requested = int(n or ORCHESTRATOR_DEFAULT_AGENTS)
    return max(1, min(requested, ORCHESTRATOR_MAX_AGENTS))


def _default_subtasks(task: str, num_agents: int) -> list[dict[str, Any]]:
    roles = [
        ("Researcher", "Gather the facts and sources needed.", ["web_search", "fetch_url"]),
        ("Analyst", "Analyse the gathered material and identify the key points.", []),
        ("Engineer", "Produce any code, data or concrete artefact required.", ["run_python"]),
        ("Reviewer", "Check the work for gaps, errors and contradictions.", []),
    ]
    subtasks: list[dict[str, Any]] = []
    for i in range(num_agents):
        label, instruction, tools = roles[i % len(roles)]
        subtasks.append(
            {
                "agent_id": i + 1,
                "label": label,
                "task": f"{instruction}\n\nOverall task: {task}",
                "tools": tools,
                "context": task,
            }
        )
    return subtasks


def plan_subtasks(
    task: str,
    num_agents: int,
    model: str,
    ollama_url: str,
    *,
    usage_cb: Callable[[dict], None] | None = None,
    read_timeout: float = 300.0,
) -> list[dict[str, Any]]:
    """Decompose *task* into ``num_agents`` sub-tasks (LLM, with fallback)."""
    if model and ollama_url:
        try:
            prompt = build_planner_prompt(task, num_agents)
            result = llm_chat_safe(
                [{"role": "user", "content": prompt}],
                model,
                ollama_url,
                format="json",
                temperature=0.2,
                read_timeout=read_timeout,
                num_ctx=MOE_NUM_CTX,
                error_prefix="[orchestrator plan",
            )
            if usage_cb is not None:
                usage_cb(result.get("usage") or {})
            plan = parse_plan(result.get("content") or "", num_agents)
            if plan:
                return plan[:num_agents]
        except Exception as e:  # noqa: BLE001 - planning is best-effort
            print(f"[orchestrator] planning failed: {e}")
    return _default_subtasks(task, num_agents)


# ── conflict resolution ───────────────────────────────────────────────────


def build_conflict_prompt(task: str, outputs: list[dict[str, Any]]) -> str:
    section = "\n".join(
        f"--- Agent {o['agent_id']} ({o.get('label', '')}) ---\n{o.get('output', '')[:4000]}"
        for o in outputs
    )
    return f"""You are a conflict detector. Several agents answered the same task.

TASK:
{task[:3000]}

AGENT OUTPUTS:
{section}

Identify factual contradictions between agents (ignore differences in wording or
emphasis). Respond with ONLY a JSON object:
{{"conflicts": [{{"topic": "...", "agents": [1, 2], "positions": ["...", "..."],
  "resolution": "which position is better supported and why"}}]}}
Return {{"conflicts": []}} when the agents agree."""


def parse_conflicts(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            return []
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(parsed, dict):
        return []
    conflicts = parsed.get("conflicts")
    if not isinstance(conflicts, list):
        return []
    normalized: list[dict[str, Any]] = []
    for c in conflicts:
        if isinstance(c, dict):
            normalized.append(
                {
                    "topic": str(c.get("topic", ""))[:200],
                    "agents": c.get("agents", []),
                    "positions": [str(p) for p in c.get("positions", [])][:4],
                    "resolution": str(c.get("resolution", ""))[:600],
                }
            )
    return normalized


def detect_conflicts(
    task: str,
    outputs: list[dict[str, Any]],
    model: str,
    ollama_url: str,
    *,
    usage_cb: Callable[[dict], None] | None = None,
) -> list[dict[str, Any]]:
    if len(outputs) < 2 or not model or not ollama_url:
        return []
    try:
        result = llm_chat_safe(
            [{"role": "user", "content": build_conflict_prompt(task, outputs)}],
            model,
            ollama_url,
            format="json",
            temperature=0.0,
            num_predict=700,
            num_ctx=MOE_NUM_CTX,
            error_prefix="[orchestrator conflict",
        )
    except Exception as e:  # noqa: BLE001
        print(f"[orchestrator] conflict detection failed: {e}")
        return []
    if usage_cb is not None:
        usage_cb(result.get("usage") or {})
    return parse_conflicts(result.get("content") or "")


# ── arena scoring ─────────────────────────────────────────────────────────


def build_judge_prompt(task: str, candidates: list[dict[str, Any]]) -> str:
    section = "\n".join(
        f"--- Candidate {c['agent_id']} ---\n{c.get('output', '')[:4000]}" for c in candidates
    )
    return f"""You are a strict judge evaluating candidate answers to the same task.

TASK:
{task[:3000]}

CANDIDATES:
{section}

Score each candidate 0-10 on correctness, completeness and clarity. Respond with
ONLY a JSON object:
{{"scores": [{{"agent_id": 1, "score": 8.5, "reason": "..."}}],
  "winner": 1, "reason": "why the winner is best"}}"""


def parse_judgement(text: str) -> dict[str, Any]:
    if not text:
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            return {}
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except (json.JSONDecodeError, TypeError):
            return {}
    if not isinstance(parsed, dict):
        return {}
    scores = parsed.get("scores")
    return {
        "scores": scores if isinstance(scores, list) else [],
        "winner": parsed.get("winner"),
        "reason": str(parsed.get("reason", ""))[:600],
    }


def _max_concurrency(num_agents: int, ollama_url: str, model: str) -> int:
    if ORCHESTRATOR_MAX_CONCURRENCY > 0:
        return max(1, min(ORCHESTRATOR_MAX_CONCURRENCY, num_agents))
    from palimind.llm.mixture_of_expert.orchestrator import _max_concurrency as moe_concurrency

    return moe_concurrency(num_agents, ollama_url, model)


# ── orchestration ─────────────────────────────────────────────────────────


async def orchestrate(
    task: str,
    *,
    model: str,
    ollama_url: str,
    light_model: str = "",
    definition: Any | None = None,
    working_root: Path | None = None,
    num_agents: int | None = None,
    mode: str = "fan_out",
    emit: Callable[[str, dict], Awaitable[None]] | None = None,
    max_concurrency: int | None = None,
    time_budget_s: float = 1800.0,
    approval_provider: Callable[[dict], dict] | None = None,
) -> dict[str, Any]:
    """Run a multi-agent orchestration and return its result.

    Returns ``{"mode", "output", "outputs", "blackboard", "conflicts",
    "judgement", "usage", "timings"}``.
    """
    started = time.monotonic()
    num = clamp_agent_count(num_agents)
    resolved_mode = mode if mode in ORCHESTRATION_MODES else "fan_out"

    async def send(etype: str, payload: dict[str, Any]) -> None:
        if emit is not None:
            try:
                await emit(etype, payload)
            except Exception as e:  # noqa: BLE001
                print(f"[orchestrator] emit failed ({etype}): {e}")

    # Tools are sandboxed to the working root; set the process-wide context once
    # (parallel workers share it, exactly like the MoE pipeline).
    set_tool_context(working_root, ollama_url, model, light_model or model)

    usage: dict[str, dict] = {}
    timings: dict[str, float] = {}

    def _capture(stage: str, result: dict) -> None:
        u = result.get("usage") or {}
        if u:
            usage[stage] = u

    loop = asyncio.get_running_loop()
    concurrency = max_concurrency or _max_concurrency(num, ollama_url, model)
    semaphore = asyncio.Semaphore(concurrency)

    subtasks: list[dict[str, Any]]
    if resolved_mode == "arena":
        subtasks = [
            {
                "agent_id": i + 1,
                "label": f"Candidate {i + 1}",
                "task": task,
                "tools": list(getattr(definition, "tools", []) or []),
                "context": task,
            }
            for i in range(num)
        ]
    else:
        t = time.monotonic()
        subtasks = await asyncio.to_thread(
            plan_subtasks,
            task,
            num,
            light_model or model,
            ollama_url,
            usage_cb=lambda u: _capture("plan", {"usage": u}),
        )
        timings["plan"] = time.monotonic() - t

    await send(
        "orchestrator:plan",
        {
            "mode": resolved_mode,
            "agents": [
                {
                    "agent_id": s["agent_id"],
                    "label": s.get("label", ""),
                    "task": s.get("task", "")[:200],
                    "tools": s.get("tools", []),
                }
                for s in subtasks
            ],
        },
    )

    blackboard = Blackboard()
    timeout = max(30.0, time_budget_s - (time.monotonic() - started))

    async def run_one(sub_task: dict[str, Any], idx: int) -> dict[str, Any]:
        agent_id = sub_task.get("agent_id", idx + 1)
        label = sub_task.get("label") or f"Agent {agent_id}"
        await send(
            "orchestrator:agent_start",
            {"agent_id": agent_id, "label": label, "task": sub_task.get("task", "")[:200]},
        )

        def on_step(text: str) -> None:
            asyncio.run_coroutine_threadsafe(
                send("orchestrator:agent_step", {"agent_id": agent_id, "text": text}), loop
            )

        agent_usage: dict[str, int] = {}
        async with semaphore:
            # Inject the blackboard snapshot gathered so far so agents that
            # start later benefit from earlier findings (shared communication).
            briefing = blackboard.render()
            output = await asyncio.to_thread(
                run_agent,
                agent_id,
                sub_task,
                model,
                ollama_url,
                None,
                on_step,
                definition=definition,
                briefing=briefing,
                approval_provider=approval_provider,
                usage_cb=agent_usage.update,
            )
        if agent_usage:
            usage[f"agent_{agent_id}"] = dict(agent_usage)

        blackboard.post(agent_id, label, output, task=sub_task.get("task", ""))
        await send(
            "orchestrator:blackboard",
            {"agent_id": agent_id, "label": label, "output": output[:1500]},
        )
        await send("orchestrator:agent_complete", {"agent_id": agent_id, "label": label})
        return {
            "agent_id": agent_id,
            "label": label,
            "task": sub_task.get("task", ""),
            "output": output,
        }

    # Run in bounded parallel; use asyncio.wait so a global budget is honoured.
    t = time.monotonic()
    tasks = [asyncio.ensure_future(run_one(s, i)) for i, s in enumerate(subtasks)]
    try:
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        for p in pending:
            p.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        outputs = [fut.result() for fut in done if not fut.cancelled() and fut.exception() is None]
    except Exception as e:  # noqa: BLE001
        for task_obj in tasks:
            task_obj.cancel()
        print(f"[orchestrator] execution failed: {e}")
        outputs = []
    outputs.sort(key=lambda o: o.get("agent_id", 0))
    timings["agents"] = time.monotonic() - t

    # ── conflict resolution ─────────────────────────────────────────────
    conflicts: list[dict[str, Any]] = []
    if ORCHESTRATOR_CONFLICT_RESOLUTION and resolved_mode == "fan_out" and len(outputs) > 1:
        await send("orchestrator:conflict_check", {"agents": len(outputs)})
        conflicts = await asyncio.to_thread(
            detect_conflicts,
            task,
            outputs,
            light_model or model,
            ollama_url,
            usage_cb=lambda u: _capture("conflict", {"usage": u}),
        )
        if conflicts:
            await send("orchestrator:conflict", {"conflicts": conflicts})

    # ── arena judging ───────────────────────────────────────────────────
    judgement: dict[str, Any] = {}
    if resolved_mode == "arena" and outputs:
        await send("orchestrator:judging", {"candidates": len(outputs)})
        try:
            result = await asyncio.to_thread(
                llm_chat_safe,
                [{"role": "user", "content": build_judge_prompt(task, outputs)}],
                light_model or model,
                ollama_url,
                format="json",
                temperature=0.0,
                num_predict=800,
                num_ctx=MOE_NUM_CTX,
                error_prefix="[orchestrator judge",
            )
            _capture("judge", result)
            judgement = parse_judgement(result.get("content") or "")
        except Exception as e:  # noqa: BLE001
            print(f"[orchestrator] judging failed: {e}")

    # ── synthesis ───────────────────────────────────────────────────────
    await send("orchestrator:synthesis_start", {})
    t = time.monotonic()
    if resolved_mode == "arena" and judgement.get("winner") is not None:
        winner = next((o for o in outputs if o.get("agent_id") == judgement["winner"]), None)
        synthesis = (winner or outputs[0]).get("output", "") if outputs else ""
    elif outputs:
        synthesis_prompt = build_synthesis_prompt(task, outputs)
        if conflicts:
            resolution = "\n".join(
                f"- {c.get('topic', '')}: {c.get('resolution', '')}" for c in conflicts
            )
            synthesis_prompt += (
                "\n\nCONFLICT RESOLUTION (the reviewer identified these disagreements; "
                "adopt the better-supported position and say so):\n" + resolution
            )
        try:
            result = await asyncio.to_thread(
                llm_chat_safe,
                [{"role": "user", "content": synthesis_prompt}],
                model,
                ollama_url,
                read_timeout=600.0,
                num_ctx=MOE_NUM_CTX,
                error_prefix="[orchestrator synthesis",
            )
            _capture("synthesis", result)
            synthesis = result.get("content") or ""
        except Exception as e:  # noqa: BLE001
            print(f"[orchestrator] synthesis failed: {e}")
            synthesis = "\n\n".join(o.get("output", "") for o in outputs)
    else:
        synthesis = "[Orchestration produced no agent output]"
    timings["synthesis"] = time.monotonic() - t

    timings["total"] = time.monotonic() - started
    await send(
        "orchestrator:complete",
        {"output": synthesis, "conflicts": len(conflicts), "mode": resolved_mode},
    )
    return {
        "mode": resolved_mode,
        "output": synthesis,
        "outputs": outputs,
        "blackboard": blackboard.entries(),
        "conflicts": conflicts,
        "judgement": judgement,
        "usage": usage,
        "timings": timings,
    }


__all__ = [
    "Blackboard",
    "ORCHESTRATION_MODES",
    "build_conflict_prompt",
    "build_judge_prompt",
    "clamp_agent_count",
    "detect_conflicts",
    "orchestrate",
    "parse_conflicts",
    "parse_judgement",
    "plan_subtasks",
]
