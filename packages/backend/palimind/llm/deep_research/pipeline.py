from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from palimind.llm.mixture_of_expert.agents import run_agent
from palimind.llm.mixture_of_expert.llm import llm_chat_safe
from palimind.llm.mixture_of_expert.tools import set_tool_context
from palimind.settings import (
    DR_MAX_AGENT_ITERATIONS,
    DR_MAX_CONCURRENCY,
    DR_MAX_SEARCH_RESULTS,
    DR_NUM_CTX,
    DR_VERIFY,
)

# ── prompt builders ────────────────────────────────────────────────────────


def build_research_plan_prompt(
    user_query: str,
    num_subtopics: int = 5,
    memory_context: str = "",
) -> str:
    memory_section = ""
    if memory_context and memory_context.strip():
        memory_section = f"\n\nConversation Memory Context:\n{memory_context.strip()}\n"

    return f"""You are a research planning orchestrator. The user wants a deep research report on:

"{user_query}"
{memory_section}
Your job is to break this topic into {num_subtopics} specific, non-overlapping research sub-topics
that together provide comprehensive coverage of the subject.

Each sub-topic should be:
- Specific and focused (not too broad)
- Researchable through web sources
- Distinct from the other sub-topics
- Together they should cover the full scope of the user's query

Return ONLY a valid JSON array of {num_subtopics} objects with these exact fields:
- "subtopic_id": integer (1 to {num_subtopics}),
- "title": string (descriptive title for this research area),
- "research_question": string (the specific question this sub-topic investigates),
- "search_queries": list of strings (2-3 specific search queries to use),

Example:
[
  {{"subtopic_id": 1, "title": "Background and Context", "research_question": "What is the history and current state of this topic?", "search_queries": ["history of X", "current state of X 2025"]}},
  {{"subtopic_id": 2, "title": "Key Developments", "research_question": "What are the most important recent developments?", "search_queries": ["latest developments in X", "X breakthroughs 2025"]}}
]

Return ONLY the raw JSON array."""


def build_research_agent_prompt(
    subtopic_id: int,
    title: str,
    research_question: str,
    search_queries: list[str],
    worker_model: str,
    briefing: str = "",
) -> str:
    queries_str = "\n".join(f"  - {q}" for q in search_queries)
    briefing_section = ""
    if briefing and briefing.strip():
        briefing_section = (
            f"\n\nSHARED WEB BRIEFING (already gathered — use as starting point, "
            f"then search for more specific information):\n{briefing.strip()}\n"
        )

    return f"""You are Research Agent {subtopic_id} ("{title}"). You are running with model ({worker_model}).

Your research question: {research_question}

Suggested search queries to try:
{queries_str}
{briefing_section}
Your task:
1. Perform thorough web research on your assigned sub-topic using the suggested search queries and any additional queries you deem necessary.
2. Fetch and read the most relevant pages to gather detailed information.
3. Take notes on key facts, figures, dates, and findings.
4. When done, write a comprehensive research summary (500-1000 words) covering your sub-topic.

CRITICAL INSTRUCTIONS:
- Use web_search and fetch_url tools extensively — this is deep research, not a quick answer.
- Search from multiple angles to get diverse sources.
- Fetch full pages when search results look promising.
- Include specific facts, numbers, dates, and quotes where available.
- Note any conflicting information you find.

When using a tool (if native tool calls are unavailable):
  TOOL: tool_name
  ARGS: key1=value1, key2=value2
(ARGS may also be a one-line JSON object.)

When done, output your final result using:
  FINAL_ANSWER:
  <your complete research summary here>"""


def build_deep_synthesis_prompt(
    user_query: str,
    research_outputs: list[dict[str, Any]],
    memory_context: str = "",
) -> str:
    outputs_section = ""
    for ro in research_outputs:
        outputs_section += (
            f"\n--- Research Finding: {ro.get('title', 'Unknown')} ---\n"
            f"Research Question: {ro.get('research_question', '')}\n"
            f"{ro.get('output', 'No output')}\n"
        )

    memory_section = ""
    if memory_context and memory_context.strip():
        memory_section = f"\n\nConversation Memory Context:\n{memory_context.strip()}\n"

    return f"""You are the lead research synthesizer. The user asked for a deep research report on:
"{user_query}"
{memory_section}
Your research agents have completed their investigations. Here are their findings:
{outputs_section}

Synthesize these findings into a comprehensive, well-structured deep research report.

REPORT STRUCTURE:
1. **Executive Summary** — 2-3 paragraph overview of the key findings
2. **Background & Context** — relevant background information
3. **Key Findings by Area** — organized by research sub-topic, with clear headings
4. **Analysis & Implications** — what the findings mean, trends, patterns
5. **Conflicting Viewpoints** — any disagreements between sources (if applicable)
6. **Conclusion** — summary of the most important takeaways
7. **Sources** — list of key sources referenced

REQUIREMENTS:
- Be thorough and detailed — this is a deep research report, not a summary
- Include specific facts, figures, dates, and data points
- Attribute information to the relevant research area
- Use markdown formatting with headers, bullet points, and clear structure
- Resolve conflicts between sources where possible
- If information is missing or unclear, note it explicitly
- Minimum 2000 words for the full report"""


def build_deep_verify_prompt(
    user_query: str,
    synthesis: str,
    research_outputs: list[dict[str, Any]],
) -> str:
    outputs_section = ""
    for ro in research_outputs:
        outputs_section += (
            f"\n--- Research Finding: {ro.get('title', 'Unknown')} ---\n"
            f"{ro.get('output', 'No output')}\n"
        )

    return f"""You are a strict quality reviewer for deep research reports. The user asked:
"{user_query}"

A draft research report was synthesized from multiple research agent outputs:

--- Draft Research Report ---
{synthesis}
--- End Draft ---

The research agent outputs used to build it:
{outputs_section}

Review the draft for:
1. Did it actually answer the user's question comprehensively? (missing_scope)
2. Did it ignore important facts or research findings? (missing_facts)
3. Do any claims contradict the research outputs? (conflicts)
4. Is the structure clear and well-organized? (structure)
5. Any specific improvements? (suggestions)

Respond with ONLY a JSON object:
{{
  "answers_query": true,
  "missing_scope": "",
  "missing_facts": "",
  "conflicts": "",
  "structure": "",
  "suggestions": ""
}}"""


# ── plan parsing ───────────────────────────────────────────────────────────


def parse_research_plan(text: str, num_subtopics: int = 5) -> list[dict[str, Any]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1])
    parsed = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        if start != -1:
            inner = cleaned[start:]
            while inner:
                try:
                    parsed = json.loads(inner)
                    break
                except json.JSONDecodeError:
                    if inner.rstrip().endswith("]"):
                        cut = inner.rfind("]")
                        if cut <= 0:
                            break
                        inner = inner[:cut]
                    else:
                        closed = inner.rstrip().rstrip(",") + "]"
                        try:
                            parsed = json.loads(closed)
                            break
                        except json.JSONDecodeError:
                            cut = inner.rfind("}")
                            if cut <= 0:
                                break
                            inner = inner[: cut + 1] + "]"
    if parsed is None:
        return []
    return normalize_research_plan(parsed, num_subtopics)


def normalize_research_plan(
    plan: Any, num_subtopics: int
) -> list[dict[str, Any]]:
    if not isinstance(plan, list) or not plan:
        return []

    normalized: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for item in plan:
        if not isinstance(item, dict):
            continue
        try:
            subtopic_id = int(item.get("subtopic_id", len(normalized) + 1))
        except (TypeError, ValueError):
            subtopic_id = len(normalized) + 1
        while subtopic_id in seen_ids:
            subtopic_id += 1
        seen_ids.add(subtopic_id)

        title = str(item.get("title", "")).strip() or f"Research Area {subtopic_id}"
        research_question = str(item.get("research_question", "")).strip()
        search_queries_raw = item.get("search_queries", [])
        if not isinstance(search_queries_raw, list):
            search_queries_raw = [search_queries_raw]
        search_queries = [str(q).strip() for q in search_queries_raw if str(q).strip()]

        normalized.append(
            {
                "subtopic_id": subtopic_id,
                "title": title[:120],
                "research_question": research_question[:1000],
                "search_queries": search_queries[:5],
            }
        )
        if len(normalized) >= num_subtopics:
            break
    return normalized


def _default_research_plan(query: str, num_subtopics: int) -> list[dict[str, Any]]:
    """Fallback plan when the orchestrator LLM fails to produce valid JSON."""
    return [
        {
            "subtopic_id": i + 1,
            "title": f"Research Area {i + 1}",
            "research_question": f"Investigate aspect {i + 1} of: {query}",
            "search_queries": [query],
        }
        for i in range(num_subtopics)
    ]


# ── pipeline ──────────────────────────────────────────────────────────────


async def run_deep_research_pipeline(
    user_query: str,
    ollama_url: str,
    orchestrator_model: str,
    worker_model: str,
    num_subtopics: int = 5,
    on_progress: Callable[[dict], Awaitable[None]] | None = None,
    short_term: list[dict] | None = None,
    mid_term_summary: str | None = None,
    long_term_episodes: list[dict] | None = None,
    root: Path | None = None,
    worker_url: str | None = None,
) -> dict[str, Any]:
    """Deep Research pipeline: plans sub-topics, dispatches parallel research
    agents with web access, then synthesizes a comprehensive research report."""
    from palimind.memory.hierarchical import format_hierarchical_memory_context

    memory_ctx = format_hierarchical_memory_context(mid_term_summary, long_term_episodes or [])

    async def emit(event: dict):
        if on_progress:
            await on_progress(event)

    # Expose workspace context to agent tools
    light_model = ""
    if root is not None:
        try:
            from palimind.config import load_config

            cfg = load_config(root)
            light_model = cfg.get("light_model", "") or cfg.get("chat_model", "")
        except Exception:
            light_model = ""
    light_url = worker_url or ollama_url
    if light_model:
        from palimind.opencode.router import resolve_model

        light_model, light_url, light_note = resolve_model(
            light_model, worker_url or ollama_url, fallback_model=worker_model
        )
        if light_note:
            print(f"[deep-research] {light_note}")
    set_tool_context(root, worker_url or ollama_url, worker_model, light_model)

    # ── usage telemetry / stage timings ──────────────────────────────────
    usage: dict[str, dict] = {}
    timings: dict[str, float] = {}
    t_start = time.monotonic()

    def _capture(stage: str, result: dict) -> None:
        u = result.get("usage") or {}
        if u:
            usage[stage] = u

    # ── Phase 1: Plan research sub-topics ────────────────────────────────
    await emit({"type": "planning", "text": "Planning deep research — analyzing query and designing research plan..."})
    t = time.monotonic()
    plan_prompt = build_research_plan_prompt(
        user_query, num_subtopics, memory_context=memory_ctx
    )
    plan_result = await asyncio.to_thread(
        llm_chat_safe,
        [{"role": "user", "content": plan_prompt}],
        orchestrator_model,
        ollama_url,
        format="json",
        temperature=0.2,
        read_timeout=600.0,
        num_ctx=DR_NUM_CTX,
        error_prefix="[research-planner error",
    )
    _capture("planner", plan_result)
    timings["plan"] = time.monotonic() - t
    plan = parse_research_plan(plan_result["content"], num_subtopics)

    if not plan:
        plan = _default_research_plan(user_query, num_subtopics)

    await emit({"type": "planning", "text": f"Research plan created with {len(plan)} sub-topics. Dispatching research agents..."})

    # ── Phase 2: Shared web briefing ─────────────────────────────────────
    briefing = ""
    from palimind.core.web_search import perform_web_search

    await emit({"type": "planning", "text": "Gathering shared web briefing for all research agents..."})
    t = time.monotonic()
    briefing = await asyncio.to_thread(
        perform_web_search, user_query, max_results=DR_MAX_SEARCH_RESULTS, fetch_content=True
    )
    timings["briefing"] = time.monotonic() - t

    # ── Phase 3: Execute research agents (parallel) ──────────────────────
    loop = asyncio.get_running_loop()
    semaphore = asyncio.Semaphore(DR_MAX_CONCURRENCY)

    async def run_research_agent(subtopic: dict, idx: int) -> dict:
        subtopic_id = subtopic.get("subtopic_id", idx + 1)
        title = subtopic.get("title", f"Research {subtopic_id}")
        research_question = subtopic.get("research_question", "")[:80]
        search_queries = subtopic.get("search_queries", [])

        await emit(
            {
                "type": "agent_start",
                "agent_id": subtopic_id,
                "label": title,
                "task": research_question,
            }
        )

        def on_step_callback(step_text: str):
            asyncio.run_coroutine_threadsafe(
                emit(
                    {
                        "type": "agent_step",
                        "agent_id": subtopic_id,
                        "text": step_text,
                    }
                ),
                loop,
            )

        agent_usage: dict[str, int] = {}

        async with semaphore:
            output = await asyncio.to_thread(
                run_agent,
                subtopic_id,
                {
                    "agent_id": subtopic_id,
                    "label": title,
                    "task": f"Research question: {research_question}\nSearch queries: {', '.join(search_queries)}",
                    "tools": ["web_search", "fetch_url"],
                    "context": user_query,
                },
                worker_model,
                worker_url or ollama_url,
                DR_MAX_AGENT_ITERATIONS,
                on_step_callback,
                briefing=briefing,
                usage_cb=agent_usage.update,
            )
        if agent_usage:
            usage[f"agent_{subtopic_id}"] = dict(agent_usage)

        await emit(
            {
                "type": "agent_complete",
                "agent_id": subtopic_id,
                "label": title,
            }
        )
        return {
            "subtopic_id": subtopic_id,
            "title": title,
            "research_question": research_question,
            "search_queries": search_queries,
            "output": output,
        }

    tasks = [run_research_agent(st, i) for i, st in enumerate(plan)]
    t = time.monotonic()
    research_outputs = list(await asyncio.gather(*tasks))
    timings["agents"] = time.monotonic() - t

    # ── Phase 4: Synthesize research report ──────────────────────────────
    await emit({"type": "synthesizing", "text": "Synthesizing comprehensive research report..."})
    t = time.monotonic()
    synthesis_prompt = build_deep_synthesis_prompt(
        user_query, research_outputs, memory_context=memory_ctx
    )
    synthesis_result = await asyncio.to_thread(
        llm_chat_safe,
        [{"role": "user", "content": synthesis_prompt}],
        orchestrator_model,
        ollama_url,
        read_timeout=600.0,
        num_ctx=DR_NUM_CTX,
        error_prefix="[deep-synthesis error",
    )
    _capture("synthesis", synthesis_result)
    timings["synthesis"] = time.monotonic() - t
    synthesis = synthesis_result["content"]

    # ── Phase 5: Verify / refine ─────────────────────────────────────────
    if DR_VERIFY and synthesis:
        await emit({"type": "verifying", "text": "Verifying research report quality..."})
        verify_model = light_model or orchestrator_model
        verify_prompt = build_deep_verify_prompt(user_query, synthesis, research_outputs)
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
            num_ctx=DR_NUM_CTX,
            error_prefix="[deep-verify error",
        )
        _capture("verify", verify_result)
        timings["verify"] = time.monotonic() - t
        try:
            critique = json.loads(verify_result["content"])
        except (json.JSONDecodeError, TypeError):
            critique = {}
        if _needs_refinement(critique):
            feedback = _format_verify_feedback(critique)
            await emit({"type": "verifying", "text": "Refining research report after review..."})
            refined_prompt = (
                f"{synthesis_prompt}\n\nREVIEW FEEDBACK (address these issues and "
                f"return the improved final report):\n{feedback}"
            )
            refined_result = await asyncio.to_thread(
                llm_chat_safe,
                [{"role": "user", "content": refined_prompt}],
                orchestrator_model,
                ollama_url,
                read_timeout=600.0,
                num_ctx=DR_NUM_CTX,
                error_prefix="[deep-synthesis error",
            )
            _capture("synthesis_refine", refined_result)
            if refined_result["content"]:
                synthesis = refined_result["content"]

    timings["total"] = time.monotonic() - t_start
    await emit({"type": "complete"})
    return {
        "plan": plan,
        "outputs": research_outputs,
        "synthesis": synthesis,
        "usage": usage,
        "timings": timings,
    }


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
        ("structure", "Structure issues"),
        ("suggestions", "Suggestions"),
    ):
        value = str(critique.get(key) or "").strip()
        if value:
            lines.append(f"- {label}: {value}")
    return (
        "\n".join(lines)
        if lines
        else "Reviewer found no specific issues; make the report more precise."
    )
