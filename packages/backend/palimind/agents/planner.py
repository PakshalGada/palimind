"""Agent planning mode: plan-then-execute with user approval.

Phase 4.4 adds a plan step in front of tool execution. A run can be configured
with one of three planning modes:

* ``off``    — execute immediately (current behaviour).
* ``review`` — generate a plan, surface it to the user, wait for approval or
  edits, then execute.
* ``auto``   — generate a plan and proceed without waiting.

The module owns plan generation (one LLM call, deterministic fallback),
persistence (``~/.palimind/agents/plans``), templates for common tasks,
step-level status tracking and rollback of file mutations on failure.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from palimind.settings import PLAN_MAX_STEPS

PLANNING_MODES: tuple[str, ...] = ("off", "review", "auto")

PLANS_DIR = Path.home() / ".palimind" / "agents" / "plans"

# Reusable starting points for common tasks. Each template is a list of steps.
PLAN_TEMPLATES: dict[str, dict[str, Any]] = {
    "code-change": {
        "name": "Code change",
        "description": "Safely modify code: understand, change, test, review.",
        "steps": [
            {"title": "Read the relevant code", "tool": "read_file", "args": {}},
            {"title": "Locate dependencies and callers", "tool": "grep_files", "args": {}},
            {"title": "Implement the change", "tool": "write_file", "args": {}},
            {"title": "Run the tests", "tool": "run_python", "args": {}},
            {"title": "Review the diff and edge cases", "tool": "", "args": {}},
        ],
    },
    "research-report": {
        "name": "Research report",
        "description": "Gather, verify and synthesise sources into a report.",
        "steps": [
            {"title": "Break the question into sub-questions", "tool": "", "args": {}},
            {"title": "Search the web for each sub-question", "tool": "web_search", "args": {}},
            {"title": "Read the most authoritative sources", "tool": "fetch_url", "args": {}},
            {"title": "Cross-check claims across sources", "tool": "", "args": {}},
            {"title": "Write the cited report", "tool": "", "args": {}},
        ],
    },
    "data-analysis": {
        "name": "Data analysis",
        "description": "Load, clean, analyse and summarise a dataset.",
        "steps": [
            {"title": "Load and inspect the data", "tool": "csv_query", "args": {}},
            {"title": "Clean and validate the data", "tool": "run_python", "args": {}},
            {"title": "Compute the key metrics", "tool": "run_python", "args": {}},
            {"title": "Check results against assumptions", "tool": "", "args": {}},
            {"title": "Summarise findings", "tool": "", "args": {}},
        ],
    },
    "content-draft": {
        "name": "Content draft",
        "description": "Research, outline, draft and edit a piece of content.",
        "steps": [
            {"title": "Clarify audience, tone and constraints", "tool": "", "args": {}},
            {"title": "Gather supporting facts", "tool": "document_search", "args": {}},
            {"title": "Draft an outline", "tool": "", "args": {}},
            {"title": "Write the draft", "tool": "", "args": {}},
            {"title": "Edit for clarity and length", "tool": "", "args": {}},
        ],
    },
}


def list_templates() -> list[dict[str, Any]]:
    return [{"id": key, **value} for key, value in PLAN_TEMPLATES.items()]


def build_plan_from_template(template_id: str, task: str = "") -> dict[str, Any]:
    template = PLAN_TEMPLATES.get(template_id)
    if template is None:
        return new_plan(task, [])
    return new_plan(task, template["steps"])


def new_plan(
    task: str,
    steps: list[dict[str, Any]] | None = None,
    *,
    agent_id: str = "",
    notes: str = "",
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "agent_id": agent_id,
        "task": task,
        "notes": notes,
        "created_at": time.time(),
        "updated_at": time.time(),
        "status": "pending",
        "steps": normalize_steps(steps or []),
    }


def normalize_steps(steps: list[Any]) -> list[dict[str, Any]]:
    """Validate/normalize a list of plan steps into a safe, bounded list."""
    from palimind.llm.mixture_of_expert.tools import get_tool_names

    valid_tools = set(get_tool_names())
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(steps):
        if not isinstance(raw, dict):
            continue
        tool = str(raw.get("tool", "") or "").strip()
        if tool and tool not in valid_tools:
            tool = ""
        try:
            step_id = int(raw.get("id", idx + 1))
        except (TypeError, ValueError):
            step_id = idx + 1
        args = raw.get("args")
        normalized.append(
            {
                "id": step_id,
                "title": str(raw.get("title", "") or raw.get("description", ""))[:200],
                "description": str(raw.get("description", ""))[:1000],
                "tool": tool,
                "args": args if isinstance(args, dict) else {},
                "status": str(raw.get("status", "pending")),
                "result": str(raw.get("result", ""))[:4000],
                "approved": bool(raw.get("approved", False)),
            }
        )
        if len(normalized) >= PLAN_MAX_STEPS:
            break
    return normalized


def parse_plan_json(text: str) -> list[dict[str, Any]]:
    """Parse a plan array from an LLM response, tolerating fences/prose."""
    if not text:
        return []
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    parsed: Any = None
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end > start:
            try:
                parsed = json.loads(cleaned[start : end + 1])
            except (json.JSONDecodeError, TypeError):
                parsed = None
    if isinstance(parsed, dict):
        parsed = parsed.get("steps")
    if not isinstance(parsed, list):
        return []
    return normalize_steps(parsed)


def build_plan_prompt(
    task: str,
    *,
    max_steps: int = PLAN_MAX_STEPS,
    available_tools: list[str] | None = None,
    success_criteria: str = "",
) -> str:
    tools = ", ".join(available_tools or []) or "(none)"
    criteria = ""
    if success_criteria and success_criteria.strip():
        criteria = f"\nSuccess criteria: {success_criteria.strip()}\n"
    return f"""You are a planning agent. Before acting, produce a short, ordered plan.

TASK:
{task[:4000]}
{criteria}
Available tools: {tools}

Return ONLY a JSON array of at most {max_steps} steps. Each step:
{{"id": 1, "title": "short imperative title", "description": "what to do",
  "tool": "tool_name or empty string", "args": {{}}}}

Rules:
- Only use tools from the available list.
- Prefer the fewest steps that fully satisfy the task.
- Include a final verification/review step.
Return ONLY the raw JSON array."""


def generate_plan(
    task: str,
    model: str = "",
    ollama_url: str = "",
    *,
    agent_id: str = "",
    available_tools: list[str] | None = None,
    success_criteria: str = "",
    usage_cb: Any | None = None,
    read_timeout: float = 300.0,
) -> dict[str, Any]:
    """Generate a plan for *task*.

    Uses the LLM when available, otherwise a deterministic multi-step fallback.
    Always returns a persisted, valid plan dict.
    """
    steps: list[dict[str, Any]] = []
    if model and ollama_url:
        try:
            from palimind.llm.mixture_of_expert.llm import llm_chat_safe

            result = llm_chat_safe(
                [
                    {
                        "role": "user",
                        "content": build_plan_prompt(
                            task,
                            available_tools=available_tools,
                            success_criteria=success_criteria,
                        ),
                    }
                ],
                model,
                ollama_url,
                format="json",
                temperature=0.1,
                read_timeout=read_timeout,
                error_prefix="[planner",
            )
            if usage_cb is not None:
                try:
                    usage_cb(result.get("usage") or {})
                except Exception:  # noqa: BLE001
                    pass
            steps = parse_plan_json(result.get("content") or "")
        except Exception as e:  # noqa: BLE001 - planner is best-effort
            print(f"[planner] plan generation failed: {e}")

    if not steps:
        steps = _fallback_steps(task, available_tools)
    plan = new_plan(task, steps, agent_id=agent_id)
    return plan


def _fallback_steps(task: str, available_tools: list[str] | None) -> list[dict[str, Any]]:
    tools = set(available_tools or [])
    steps: list[dict[str, Any]] = [
        {"title": "Understand the task and gather context", "tool": "", "args": {}},
    ]
    if "web_search" in tools:
        steps.append({"title": "Search for current information", "tool": "web_search", "args": {}})
    if "document_search" in tools:
        steps.append({"title": "Search the knowledge base", "tool": "document_search", "args": {}})
    if "read_file" in tools or "list_files" in tools:
        steps.append({"title": "Read the relevant files", "tool": "read_file", "args": {}})
    steps.append({"title": "Produce the result", "tool": "", "args": {}})
    steps.append({"title": "Verify the result against the task", "tool": "", "args": {}})
    return normalize_steps(steps)


# ── persistence ───────────────────────────────────────────────────────────


def _plan_path(plan_id: str) -> Path:
    # Guard against path traversal from user-supplied ids.
    safe = "".join(c for c in str(plan_id) if c.isalnum() or c in "-_")
    return PLANS_DIR / f"{safe}.json"


def save_plan(plan: dict[str, Any]) -> dict[str, Any]:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    plan["updated_at"] = time.time()
    _plan_path(plan["id"]).write_text(json.dumps(plan, indent=2), "utf-8")
    return plan


def get_plan(plan_id: str) -> dict[str, Any] | None:
    path = _plan_path(plan_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def list_plans(limit: int = 50) -> list[dict[str, Any]]:
    if not PLANS_DIR.is_dir():
        return []
    plans: list[dict[str, Any]] = []
    for path in PLANS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text("utf-8"))
            if isinstance(data, dict):
                plans.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    plans.sort(key=lambda p: float(p.get("updated_at", 0) or 0), reverse=True)
    return plans[:limit]


def update_plan(plan_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    plan = get_plan(plan_id)
    if plan is None:
        return None
    for key in ("status", "notes", "task"):
        if key in changes:
            plan[key] = changes[key]
    if "steps" in changes and isinstance(changes["steps"], list):
        plan["steps"] = normalize_steps(changes["steps"])
    save_plan(plan)
    return plan


def delete_plan(plan_id: str) -> bool:
    path = _plan_path(plan_id)
    if path.exists():
        try:
            path.unlink()
            return True
        except OSError:
            return False
    return False


# ── approval bridge (used by runtime in "review" mode) ────────────────────

_waiters: dict[str, asyncio.Event] = {}
_results: dict[str, dict[str, Any]] = {}


async def wait_for_plan_review(plan_id: str, timeout: float = 900.0) -> dict[str, Any]:
    """Block until the user approves/edits/rejects the plan (or it times out)."""
    event = asyncio.Event()
    _waiters[plan_id] = event
    try:
        await asyncio.wait_for(event.wait(), timeout=max(1.0, timeout))
    except TimeoutError:
        return {"approved": False, "timeout": True}
    finally:
        _waiters.pop(plan_id, None)
    return _results.pop(plan_id, {"approved": False})


def resolve_plan_review(
    plan_id: str,
    approved: bool,
    steps: list[dict[str, Any]] | None = None,
) -> bool:
    """Called by the API when the user acts on a pending plan."""
    event = _waiters.get(plan_id)
    if event is None:
        return False
    if steps is not None:
        plan = update_plan(plan_id, {"steps": steps})
        if plan is not None:
            save_plan(plan)
    _results[plan_id] = {"approved": approved}
    event.set()
    return True


# ── execution with rollback ───────────────────────────────────────────────


def _snapshot_targets(
    step: dict[str, Any], working_root: Path | None
) -> tuple[str, bool, str] | None:
    """Capture the original contents of a file a mutating step will touch."""
    if step.get("tool") not in ("write_file", "search_replace"):
        return None
    args = step.get("args") or {}
    raw_path = args.get("path") or args.get("file") or args.get("filename")
    if not raw_path or working_root is None:
        return None
    target = Path(str(raw_path))
    if not target.is_absolute():
        target = Path(working_root) / target
    try:
        target = target.resolve()
        root = Path(working_root).resolve()
        if root not in target.parents and target != root:
            return None
        existed = target.exists()
        original = target.read_text("utf-8") if existed else ""
        return (str(target), existed, original)
    except (OSError, ValueError):
        return None


def _restore_snapshot(snapshot: tuple[str, bool, str]) -> None:
    path, existed, original = snapshot
    try:
        target = Path(path)
        if existed:
            target.write_text(original, "utf-8")
        elif target.exists():
            target.unlink()
    except OSError as e:
        print(f"[planner] rollback failed for {path}: {e}")


def execute_plan(
    plan: dict[str, Any],
    *,
    run_tool: Any | None = None,
    working_root: Path | None = None,
    auto_approve: bool = True,
    rollback_on_failure: bool = True,
) -> dict[str, Any]:
    """Execute a plan's tool steps in order, with file-mutation rollback.

    Steps without a tool are treated as notes and marked done. Returns the
    updated plan with per-step status/result and an ``error`` field on failure.
    """
    runner: Any = run_tool
    if runner is None:
        from palimind.llm.mixture_of_expert.tools import call_tool

        runner = call_tool

    plan["status"] = "executing"
    snapshots: list[tuple[str, bool, str]] = []
    for step in plan.get("steps", []):
        if step.get("status") in ("done", "skipped"):
            continue
        if not auto_approve and not step.get("approved"):
            step["status"] = "skipped"
            continue
        tool = step.get("tool")
        if not tool:
            step["status"] = "done"
            step["result"] = "Note step — no tool call."
            continue
        snapshot = _snapshot_targets(step, working_root)
        if snapshot is not None:
            snapshots.append(snapshot)
        try:
            result = runner(tool, **(step.get("args") or {}))
            step["status"] = "done"
            step["result"] = str(result)[:4000]
        except Exception as e:  # noqa: BLE001 - report and optionally roll back
            step["status"] = "failed"
            step["result"] = f"[error] {e}"
            plan["status"] = "failed"
            plan["error"] = str(e)
            if rollback_on_failure:
                for snap in reversed(snapshots):
                    _restore_snapshot(snap)
                plan["status"] = "rolled_back"
            break
    if plan.get("status") == "executing":
        plan["status"] = "completed"
    save_plan(plan)
    return plan


__all__ = [
    "PLANNING_MODES",
    "PLAN_TEMPLATES",
    "build_plan_from_template",
    "build_plan_prompt",
    "delete_plan",
    "execute_plan",
    "generate_plan",
    "get_plan",
    "list_plans",
    "list_templates",
    "new_plan",
    "normalize_steps",
    "parse_plan_json",
    "resolve_plan_review",
    "save_plan",
    "update_plan",
    "wait_for_plan_review",
]
