from __future__ import annotations

import json
import re
from typing import Any

AGENT_DESCRIPTIONS = [
    "Researcher - searches the web and gathers information from online sources",
    "Analyst - reads and analyzes local files, performs data analysis",
    "Engineer - writes code, creates files, and performs technical implementations",
    "Reviewer - reviews outputs, checks for quality and correctness",
]


def build_planner_prompt(
    user_query: str,
    agent_count: int = 4,
    memory_context: str = "",
    route_hints: dict[str, Any] | None = None,
) -> str:
    memory_section = ""
    if memory_context and memory_context.strip():
        memory_section = f"\n\nConversation Memory Context:\n{memory_context.strip()}\n"

    hints_section = ""
    if route_hints:
        hints = []
        if route_hints.get("needs_web"):
            hints.append(
                "- Include ONE 'Researcher (Web Search)' agent with the web_search tool "
                "to gather live, up-to-date information."
            )
        if route_hints.get("needs_docs"):
            hints.append(
                "- Include an agent with the document_search tool to consult the "
                "user's indexed workspace documents."
            )
        if route_hints.get("needs_memory"):
            hints.append(
                "- Include an agent with the memory_search tool if past conversations would help."
            )
        if route_hints.get("needs_code"):
            hints.append("- Include a coding agent with run_python and write_file tools.")
        if hints:
            hints_section = (
                "\nRouting hints (a pre-router analyzed the query):\n" + "\n".join(hints) + "\n"
            )
        if route_hints.get("simple"):
            hints_section += (
                "\nNOTE: this query is simple — assign focused, lightweight tasks "
                "rather than broad research.\n"
            )

    return f"""You are a master planning orchestrator for a Mixture-of-Experts AI system.
Your job is to analyze the user's query and dynamically create {agent_count} specialized worker agents to solve it.

The user's query is:
"{user_query}"
{memory_section}{hints_section}
Instructions:
1. Create {agent_count} custom, specialized agents tailored to solve this exact prompt.
   (Examples of dynamic titles: "Researcher (Web Search)", "Code Architect", "Math Specialist",
   "Data Summarizer", "Security Auditor", "Creative Writer", "Logic Analyst", "Translator", etc.)
2. Only assign the web_search tool to an agent if live/current information is needed for this query.
3. Assign document_search only if the query is about the user's own indexed documents.

Available tools: web_search, fetch_url, document_search, memory_search, read_file, write_file, list_files, run_python, summarize

Return ONLY a valid JSON array of {agent_count} objects with these exact fields:
- "agent_id": integer (1 to {agent_count}),
- "label": string (the custom descriptive role/title created by you, e.g. "Code Architect"),
- "task": string (specific detailed prompt/instructions for what this agent must work on),
- "tools": list of tool names from the available tools above,
- "context": string (any additional query context)

Example:
[
  {{"agent_id": 1, "label": "Researcher (Web Search)", "task": "Search the web for ...", "tools": ["web_search", "fetch_url"], "context": ""}},
  {{"agent_id": 2, "label": "Code Architect", "task": "Design the technical structure for ...", "tools": ["write_file", "run_python"], "context": ""}},
  {{"agent_id": 3, "label": "Logic Evaluator", "task": "Verify mathematical and logical constraints ...", "tools": ["run_python"], "context": ""}},
  {{"agent_id": 4, "label": "Final Reviewer", "task": "Check completeness and synthesize checks ...", "tools": [], "context": ""}}
]

Return ONLY the raw JSON array."""


def build_agent_prompt(
    agent_id: int,
    sub_task: dict[str, Any],
    worker_model: str,
) -> str:
    agent_label = sub_task.get("label") or f"Agent {agent_id}"
    tools = sub_task.get("tools", [])

    web_search_instruction = ""
    if "web_search" in tools:
        web_search_instruction = "\nIMPORTANT: You have web research tools. Execute a web search first with a relevant query to fetch up-to-date information before answering. Use fetch_url to read promising result pages in depth.\n"

    doc_search_instruction = ""
    if "document_search" in tools:
        doc_search_instruction = "\nYou have access to the user's indexed workspace documents via document_search. Use it when the task references the user's files or knowledge base.\n"

    return f"""You are Agent {agent_id} ({agent_label}). You are running with model ({worker_model}).

Your assigned task from Orchestrator:
{sub_task.get("task", "")}

Context: {sub_task.get("context", "")}

Available tools: {", ".join(tools) if tools else "(none — reason directly)"}
{web_search_instruction}{doc_search_instruction}
Think step by step to complete your task using your tools.
When using a tool (if native tool calls are unavailable):
  TOOL: tool_name
  ARGS: key1=value1, key2=value2
(ARGS may also be a one-line JSON object.)

When done, output your final result using:
  FINAL_ANSWER:
  <your complete output here>"""


def build_synthesis_prompt(
    user_query: str,
    agent_outputs: list[dict[str, Any]],
    memory_context: str = "",
) -> str:
    outputs_section = ""
    for ao in agent_outputs:
        outputs_section += (
            f"\n--- Agent {ao['agent_id']} Output ---\n{ao.get('output', 'No output')}\n"
        )

    memory_section = ""
    if memory_context and memory_context.strip():
        memory_section = f"\n\nConversation Memory Context:\n{memory_context.strip()}\n"

    return f"""You are the orchestrator. The user asked:
"{user_query}"
{memory_section}
Your expert agents produced the following results:
{outputs_section}

Synthesize these results into a single, cohesive, well-structured final answer.
Combine information, resolve any conflicts, and present a clear response to the user.
Be thorough and cite which agent provided which information."""


def parse_plan(text: str, num_workers: int = 4) -> list[dict[str, Any]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1])
    parsed = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Locate a JSON array anywhere in the response (greedy); if the
        # response is truncated mid-array, try closing it.
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
                        # Unterminated array — append the closing bracket
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
    return normalize_plan(parsed, num_workers)


def normalize_plan(
    plan: Any, num_workers: int, valid_tools: set[str] | None = None
) -> list[dict[str, Any]]:
    """Validate and normalize a parsed plan into a safe, well-formed list."""
    if valid_tools is None:
        from palimind.llm.mixture_of_expert.tools import get_tool_names

        valid_tools = set(get_tool_names())

    if not isinstance(plan, list) or not plan:
        return []

    normalized: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for item in plan:
        if not isinstance(item, dict):
            continue
        try:
            agent_id = int(item.get("agent_id", len(normalized) + 1))
        except (TypeError, ValueError):
            agent_id = len(normalized) + 1
        while agent_id in seen_ids:
            agent_id += 1
        seen_ids.add(agent_id)

        task = str(item.get("task", "")).strip()
        label = str(item.get("label", "")).strip() or f"Agent {agent_id}"
        tools_raw = item.get("tools", [])
        if not isinstance(tools_raw, list):
            tools_raw = [tools_raw]
        tools = [str(t) for t in tools_raw if str(t) in valid_tools]

        normalized.append(
            {
                "agent_id": agent_id,
                "label": label[:80],
                "task": task[:2000],
                "tools": tools,
                "context": str(item.get("context", "")).strip()[:2000],
            }
        )
        if len(normalized) >= num_workers:
            break
    return normalized


def parse_agent_output(text: str) -> str:
    marker = "FINAL_ANSWER:"
    idx = text.find(marker)
    if idx != -1:
        return text[idx + len(marker) :].strip()
    return text.strip()


def parse_tool_call(text: str) -> tuple[str | None, dict[str, Any] | None]:
    tool_match = re.search(r"TOOL:\s*(\w+)", text)
    if not tool_match:
        return None, None
    tool_name = tool_match.group(1)
    args_match = re.search(r"ARGS:\s*(.+)", text)
    args: dict[str, Any] = {}
    if args_match:
        raw_args = args_match.group(1).strip()
        # JSON object form: {"key": "value", ...}
        if raw_args.startswith("{"):
            try:
                parsed = json.loads(raw_args)
                if isinstance(parsed, dict):
                    return tool_name, parsed
            except json.JSONDecodeError:
                pass
        # key=value, key=value form
        for pair in raw_args.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                args[k.strip()] = v.strip()
    return tool_name, args if args else None
