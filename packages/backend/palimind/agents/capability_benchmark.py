"""Repeatable agent capability benchmark.

The benchmark is intentionally local and deterministic by default. It runs the
real agent loop (tool parsing, approvals, checklist guard, citations, event
stream) against either a scripted model or a live Ollama/OpenCode model.

Scenarios cover the behaviours that separate a hosted agent bot from a simple
chat completion:

* multi-step research with a source ledger and citations,
* a coding edit verified by reading the changed file,
* recovery after a tool error,
* checklist completion (including the “finish open items” guard),
* the UI follow-up/usage flow (run through the frontend test suite).

Run it with::

    python scripts/agent_capability_benchmark.py --mode scripted
    python scripts/agent_capability_benchmark.py --mode live --model qwen3.5:9b

The JSON report is suitable for `benchmarks/` and for comparing runs over time.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

from palimind.agents.citations import finalize_agent_citations
from palimind.llm.mixture_of_expert import agents as moe_agents
from palimind.llm.mixture_of_expert import tools as moe_tools

TARGET_SCORE = 0.8
DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_URL = "http://127.0.0.1:11434"


@dataclass
class ScenarioResult:
    id: str
    category: str
    name: str
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkReport:
    mode: str
    model: str
    elapsed_s: float
    target: float
    results: list[ScenarioResult]

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def score(self) -> float:
        return round(self.passed / self.total, 3) if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "model": self.model,
            "elapsed_s": round(self.elapsed_s, 2),
            "target": self.target,
            "total": self.total,
            "passed": self.passed,
            "score": self.score,
            "meets_target": self.score >= self.target,
            "scenarios": [result.to_dict() for result in self.results],
        }


# ── model runners ─────────────────────────────────────────────────────────


def scripted_model(replies: list[dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Return a deterministic model that plays back *replies*."""
    state = {"index": 0}

    def call(_messages, _model, _url, **_kwargs) -> dict[str, Any]:
        index = state["index"]
        state["index"] += 1
        reply = replies[min(index, len(replies) - 1)]
        return {
            "content": reply.get("content", ""),
            "tool_calls": list(reply.get("tool_calls", [])),
            "usage": reply.get("usage", {"prompt_tokens": 40, "completion_tokens": 20}),
        }

    return call


def _final(text: str) -> dict[str, Any]:
    return {"content": f"FINAL_ANSWER:\n{text}"}


def _tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"content": f"TOOL: {name}\nARGS: {json.dumps(args)}"}


@contextmanager
def _tool_overrides(overrides: dict[str, Callable[..., Any]]) -> Iterator[None]:
    previous = {name: moe_tools.TOOL_REGISTRY[name]["fn"] for name in overrides}
    try:
        for name, fn in overrides.items():
            moe_tools.TOOL_REGISTRY[name]["fn"] = fn
        yield
    finally:
        for name, fn in previous.items():
            moe_tools.TOOL_REGISTRY[name]["fn"] = fn


def _run_agent(
    *,
    task: str,
    tools: list[str],
    workdir: Path,
    model: str,
    ollama_url: str,
    run_id: str,
    replies: list[dict[str, Any]] | None,
    overrides: dict[str, Callable[..., Any]] | None = None,
    source_collector: list[dict[str, Any]] | None = None,
    max_iterations: int = 10,
) -> tuple[str, list[tuple[str, dict[str, Any]]], list[dict[str, Any]]]:
    collected = source_collector if source_collector is not None else []
    moe_tools.set_tool_context(
        workdir,
        ollama_url,
        model,
        model,
        source_collector=collected,
        agent_id="capability-bench",
        run_id=run_id,
        write_access=True,
        allow_network=True,
    )
    moe_tools.clear_todo(run_id)
    events: list[tuple[str, dict[str, Any]]] = []
    fake = scripted_model(replies) if replies is not None else None
    model_patch = (
        patch.object(moe_agents, "llm_chat_safe", fake) if fake is not None else nullcontext()
    )
    tool_patch = _tool_overrides(overrides or {}) if overrides else nullcontext()
    try:
        with model_patch, tool_patch:
            output = moe_agents.run_agent(
                1,
                {"task": task, "tools": tools},
                model,
                ollama_url,
                max_tool_iterations=max_iterations,
                event_cb=lambda event_type, payload: events.append((event_type, payload)),
                approval_provider=lambda _pending: {"approved": True},
            )
    finally:
        moe_tools.clear_todo(run_id)
    return output, events, collected


def _tool_results(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [
        str(payload.get("result", "")) for event, payload in events if event == "agent:tool_result"
    ]


def _tool_error_texts(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [
        result[:200]
        for result in _tool_results(events)
        if result.startswith(("Error", "Access denied", "Tool '"))
    ]


def _tool_error_count(events: list[tuple[str, dict[str, Any]]]) -> int:
    return len(_tool_error_texts(events))


def _tool_sequence(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [str(payload.get("tool", "")) for event, payload in events if event == "agent:tool_call"]


def _nudged(events: list[tuple[str, dict[str, Any]]]) -> bool:
    return any(
        event == "agent:thought" and "Checklist still has" in str(payload.get("text", ""))
        for event, payload in events
    )


def _todo_counts(events: list[tuple[str, dict[str, Any]]]) -> tuple[int, int]:
    updates = [payload for event, payload in events if event == "agent:todo"]
    open_items = 0
    if updates:
        last = updates[-1].get("items") or []
        open_items = sum(1 for item in last if item.get("status") != "completed")
    return len(updates), open_items


# ── scenarios ─────────────────────────────────────────────────────────────


RESEARCH_SOURCES = [
    {
        "url": "https://example.org/alpha",
        "title": "Alpha benchmark report",
        "snippet": "Alpha improves throughput by 38 percent after the cache change.",
        "content": "Alpha improves throughput by 38 percent after the cache change.",
    },
    {
        "url": "https://example.org/beta",
        "title": "Beta benchmark report",
        "snippet": "Beta reduces tail latency by 21 percent but costs more memory.",
        "content": "Beta reduces tail latency by 21 percent but costs more memory.",
    },
]


def _fixture_fetch(collected: list[dict[str, Any]]) -> Callable[..., str]:
    def fetch(url: str, max_chars: int = 4000) -> str:
        source = next((item for item in RESEARCH_SOURCES if item["url"] == url), None)
        if source is None:
            return f"Error: benchmark fixture has no page for {url}"
        collected.append(dict(source))
        return source["content"][:max_chars]

    return fetch


def _fixture_search(collected: list[dict[str, Any]]) -> Callable[..., str]:
    def search(query: str, max_results: int = 4) -> str:
        lines = [
            f"=== WEB SEARCH RESULTS FOR: '{query}' ===",
            "Provider: benchmark-fixture",
            f"Sources: {len(RESEARCH_SOURCES)}",
        ]
        for index, source in enumerate(RESEARCH_SOURCES[: max(1, max_results)], start=1):
            lines.extend(
                [
                    f"Source [{index}]: {source['title']}",
                    f"URL: {source['url']}",
                    f"Summary: {source['snippet']}",
                    f"Page Content:\n{source['content']}",
                    "",
                ]
            )
            collected.append(dict(source))
        return "\n".join(lines) + "=" * 39 + "\n"

    return search


def _research_scenario(mode: str, model: str, ollama_url: str, workdir: Path) -> ScenarioResult:
    collected: list[dict[str, Any]] = []
    replies = [
        _tool(
            "todo_write",
            {
                "items": [
                    {"label": "Search the benchmark reports", "status": "in_progress"},
                    {"label": "Compare the numbers", "status": "pending"},
                    {"label": "Write a cited answer", "status": "pending"},
                ]
            },
        ),
        _tool("web_search", {"query": "alpha beta cache throughput latency"}),
        _tool(
            "todo_write",
            {
                "items": [
                    {"label": "Search the benchmark reports", "status": "completed"},
                    {"label": "Compare the numbers", "status": "completed"},
                    {"label": "Write a cited answer", "status": "completed"},
                ]
            },
        ),
        _final(
            "Alpha improves throughput by 38 percent [1], while Beta reduces tail "
            "latency by 21 percent [2]."
        ),
    ]
    output, events, sources = _run_agent(
        task=(
            "Research the benchmark reports and write a short cited comparison. "
            "Use todo_write to keep a visible research plan and mark every item complete."
        ),
        tools=["todo_write", "web_search", "fetch_url"],
        workdir=workdir,
        model=model,
        ollama_url=ollama_url,
        run_id="bench-research",
        replies=replies if mode == "scripted" else None,
        overrides={
            "web_search": _fixture_search(collected),
            "fetch_url": _fixture_fetch(collected),
        },
        source_collector=collected,
        max_iterations=12,
    )
    output, citation_payload = finalize_agent_citations(output, sources)
    markers = re.findall(r"\[\d+\]", output)
    updates, open_items = _todo_counts(events)
    error_count = _tool_error_count(events)
    result_count = len(_tool_results(events)) or 1
    accuracy = 1.0 - error_count / result_count
    checks = {
        "multi_step": sum(1 for event, _ in events if event == "agent:tool_call") >= 2,
        "sources_collected": len(sources) >= 2,
        "citations_present": bool(markers) or bool((citation_payload or {}).get("sources")),
        "answer_delivered": len(output.strip()) >= 40,
        "checklist_completed": updates >= 2 and open_items == 0,
        "tool_accuracy": accuracy >= 0.8,
    }
    return ScenarioResult(
        id="research_citations",
        category="research",
        name="Multi-step research with citations",
        passed=all(checks.values()),
        checks=checks,
        metrics={
            "tool_calls": sum(1 for event, _ in events if event == "agent:tool_call"),
            "sources": len(sources),
            "citation_markers": len(markers),
            "todo_updates": updates,
            "open_todo_items": open_items,
            "tool_errors": error_count,
            "tool_accuracy": round(accuracy, 3),
            "tool_error_texts": _tool_error_texts(events),
            "tool_sequence": _tool_sequence(events),
            "nudged": _nudged(events),
            "answer_chars": len(output),
        },
        detail=output[:500],
    )


def _coding_scenario(mode: str, model: str, ollama_url: str, workdir: Path) -> ScenarioResult:
    module = workdir / "maths.py"
    module.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    replies = [
        _tool(
            "todo_write",
            {
                "items": [
                    {"label": "Read maths.py", "status": "in_progress"},
                    {"label": "Fix the bug", "status": "pending"},
                    {"label": "Verify the fix", "status": "pending"},
                ]
            },
        ),
        _tool("read_file", {"path": "maths.py"}),
        _tool(
            "search_replace",
            {"path": "maths.py", "old_string": "return a - b", "new_string": "return a + b"},
        ),
        _tool("read_file", {"path": "maths.py"}),
        _tool(
            "todo_write",
            {
                "items": [
                    {"label": "Read maths.py", "status": "completed"},
                    {"label": "Fix the bug", "status": "completed"},
                    {"label": "Verify the fix", "status": "completed"},
                ]
            },
        ),
        _final("Fixed maths.py so add() returns the sum, and verified the changed file."),
    ]
    output, events, _ = _run_agent(
        task=(
            "Fix the bug in maths.py so add(a, b) returns the sum. Read the file, "
            "make the smallest edit, then read it again to verify. Use todo_write "
            "to track the fix and mark every item complete."
        ),
        tools=["todo_write", "read_file", "search_replace"],
        workdir=workdir,
        model=model,
        ollama_url=ollama_url,
        run_id="bench-coding",
        replies=replies if mode == "scripted" else None,
        max_iterations=12,
    )
    content = module.read_text("utf-8") if module.exists() else ""
    updates, open_items = _todo_counts(events)
    error_count = _tool_error_count(events)
    result_count = len(_tool_results(events)) or 1
    accuracy = 1.0 - error_count / result_count
    tool_steps = [
        str(payload.get("tool", "")) for event, payload in events if event == "agent:tool_call"
    ]
    mutation_index = next(
        (
            index
            for index, name in enumerate(tool_steps)
            if name in {"search_replace", "write_file", "apply_patch"}
        ),
        None,
    )
    read_before_write = mutation_index is not None and "read_file" in tool_steps[:mutation_index]
    verified = mutation_index is not None and any(
        name in {"read_file", "run_python", "run_shell"}
        for name in tool_steps[mutation_index + 1 :]
    )
    checks = {
        "file_fixed": "return a + b" in content and "return a - b" not in content,
        "read_before_write": read_before_write,
        "verified": verified,
        "checklist_completed": updates >= 2 and open_items == 0,
        "answer_delivered": len(output.strip()) >= 20,
        "tool_accuracy": accuracy >= 0.8,
    }
    return ScenarioResult(
        id="coding_fix",
        category="coding",
        name="Read, edit and verify a file",
        passed=all(checks.values()),
        checks=checks,
        metrics={
            "todo_updates": updates,
            "open_todo_items": open_items,
            "tool_errors": error_count,
            "tool_accuracy": round(accuracy, 3),
            "tool_error_texts": _tool_error_texts(events),
            "tool_sequence": _tool_sequence(events),
            "nudged": _nudged(events),
            "answer_chars": len(output),
        },
        detail=output[:500],
    )


def _recovery_scenario(mode: str, model: str, ollama_url: str, workdir: Path) -> ScenarioResult:
    (workdir / "notes.txt").write_text("release notes: cache latency improved\n", encoding="utf-8")
    replies = [
        _tool("read_file", {"path": "missing.txt"}),
        _tool("read_file", {"path": "notes.txt"}),
        _final("The notes report that cache latency improved."),
    ]
    output, events, _ = _run_agent(
        task=(
            "Read missing.txt. If it does not exist, read notes.txt instead and "
            "summarise what it says."
        ),
        tools=["read_file"],
        workdir=workdir,
        model=model,
        ollama_url=ollama_url,
        run_id="bench-recovery",
        replies=replies if mode == "scripted" else None,
    )
    results = _tool_results(events)
    error_index = next(
        (i for i, result in enumerate(results) if result.startswith(("Error", "Access denied"))),
        None,
    )
    grounded = any(word in output.lower() for word in ("cache", "latency", "release"))
    checks = {
        "error_observed": error_index is not None,
        "recovered": error_index is not None
        and any(not result.startswith("Error") for result in results[error_index + 1 :]),
        "grounded_in_file": grounded,
        "answer_delivered": len(output.strip()) >= 10,
    }
    return ScenarioResult(
        id="tool_recovery",
        category="tool_use",
        name="Recover from a failed tool call",
        passed=all(checks.values()),
        checks=checks,
        metrics={
            "tool_results": len(results),
            "tool_errors": _tool_error_count(events),
            "tool_error_texts": _tool_error_texts(events),
        },
        detail=output[:500],
    )


def _checklist_scenario(mode: str, model: str, ollama_url: str, workdir: Path) -> ScenarioResult:
    replies = [
        _tool(
            "todo_write",
            {
                "items": [
                    {"label": "List the constraints", "status": "in_progress"},
                    {"label": "Draft the answer", "status": "pending"},
                ]
            },
        ),
        _final("early answer"),
        _tool(
            "todo_write",
            {
                "items": [
                    {"label": "List the constraints", "status": "completed"},
                    {"label": "Draft the answer", "status": "completed"},
                ]
            },
        ),
        _final("The answer is ready after completing both checklist items."),
    ]
    output, events, _ = _run_agent(
        task=(
            "Create a two-item checklist for this task, complete every item, and "
            "only then give the final answer."
        ),
        tools=["todo_write"],
        workdir=workdir,
        model=model,
        ollama_url=ollama_url,
        run_id="bench-checklist",
        replies=replies if mode == "scripted" else None,
        max_iterations=16,
    )
    updates, open_items = _todo_counts(events)
    nudged = _nudged(events)
    checks = {
        "checklist_created": updates >= 1,
        "guard_triggered": nudged if mode == "scripted" else True,
        "checklist_completed": updates >= 2 and open_items == 0,
        "answer_delivered": len(output.strip()) >= 10,
    }
    return ScenarioResult(
        id="checklist_completion",
        category="checklist",
        name="Complete the checklist before answering",
        passed=all(checks.values()),
        checks=checks,
        metrics={"todo_updates": updates, "open_todo_items": open_items, "nudged": nudged},
        detail=output[:500],
    )


def _ui_scenario() -> ScenarioResult:
    root = Path(__file__).resolve().parents[4]
    frontend = root / "packages" / "frontend"
    command = [
        "node",
        "--experimental-strip-types",
        "--import",
        "./tests/ts-resolve.mjs",
        "--test",
        "tests/agentCapability.test.mjs",
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=frontend,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        passed = proc.returncode == 0
        detail = (proc.stdout or proc.stderr or "").strip()[-800:]
    except Exception as exc:  # noqa: BLE001 - a missing node must not crash the report
        passed = False
        detail = f"could not run UI flow: {exc}"
    return ScenarioResult(
        id="ui_followup_flow",
        category="ui",
        name="Checklist, usage and follow-up UI flow",
        passed=passed,
        checks={"ui_test_passed": passed},
        metrics={},
        detail=detail,
    )


# ── driver ────────────────────────────────────────────────────────────────


def run_comparison(
    local_model: str = DEFAULT_MODEL,
    local_url: str = DEFAULT_URL,
    baseline_model: str = "",
    baseline_url: str = "",
    only: list[str] | None = None,
    baseline_api_key: str = "",
) -> dict[str, Any]:
    """Run the same scenarios against a local model and a hosted baseline.

    The baseline uses native OpenAI ``tool_calls`` / ``role=tool`` messages via
    ``openai_client`` — not the Ollama proxy's text fallback.
    """
    from palimind.agents.openai_client import DEFAULT_OPENAI_BASE, openai_chat_safe

    baseline_url = baseline_url or DEFAULT_OPENAI_BASE
    local = run_benchmark("live", local_model, local_url, only=only)

    def hosted_client(messages, model, _url, **kwargs):
        return openai_chat_safe(
            messages,
            model,
            baseline_url,
            api_key=baseline_api_key or None,
            **kwargs,
        )

    with patch.object(moe_agents, "llm_chat_safe", hosted_client):
        baseline = run_benchmark("live", baseline_model, baseline_url, only=only)
    local_by_id = {item.id: item for item in local.results}
    baseline_by_id = {item.id: item for item in baseline.results}
    scenarios = []
    for scenario_id in local_by_id:
        left = local_by_id[scenario_id]
        right = baseline_by_id.get(scenario_id)
        scenarios.append(
            {
                "id": scenario_id,
                "category": left.category,
                "local": left.to_dict(),
                "baseline": right.to_dict() if right else None,
                "local_pass": left.passed,
                "baseline_pass": bool(right and right.passed),
                "winner": (
                    "tie"
                    if bool(right and right.passed) == left.passed
                    else "local"
                    if left.passed
                    else "baseline"
                ),
            }
        )
    return {
        "kind": "head_to_head",
        "local": local.to_dict(),
        "baseline": baseline.to_dict(),
        "scenarios": scenarios,
        "local_score": local.score,
        "baseline_score": baseline.score,
        "score_delta": round(local.score - baseline.score, 3),
        "winner": (
            "tie"
            if local.score == baseline.score
            else "local"
            if local.score > baseline.score
            else "baseline"
        ),
    }


def run_benchmark(
    mode: str = "scripted",
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_URL,
    only: list[str] | None = None,
) -> BenchmarkReport:
    if mode not in ("scripted", "live"):
        raise ValueError("mode must be 'scripted' or 'live'")
    wanted = {item.strip() for item in (only or []) if item.strip()}
    started = time.time()
    results: list[ScenarioResult] = []
    with tempfile.TemporaryDirectory(prefix="palimind-agent-bench-") as tmp:
        workdir = Path(tmp)
        scenarios = {
            "research_citations": lambda: _research_scenario(mode, model, ollama_url, workdir),
            "coding_fix": lambda: _coding_scenario(mode, model, ollama_url, workdir),
            "tool_recovery": lambda: _recovery_scenario(mode, model, ollama_url, workdir),
            "checklist_completion": lambda: _checklist_scenario(mode, model, ollama_url, workdir),
            "ui_followup_flow": _ui_scenario,
        }
        for scenario_id, runner in scenarios.items():
            if wanted and scenario_id not in wanted:
                continue
            print(f"[bench] {scenario_id}…", file=sys.stderr, flush=True)
            results.append(runner())
    return BenchmarkReport(
        mode=mode,
        model="scripted" if mode == "scripted" else model,
        elapsed_s=time.time() - started,
        target=TARGET_SCORE,
        results=results,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the PaliMind agent capability benchmark")
    parser.add_argument("--mode", choices=("scripted", "live"), default="scripted")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--json", default="")
    parser.add_argument(
        "--only",
        default="",
        help="comma-separated scenario ids (research_citations, coding_fix, "
        "tool_recovery, checklist_completion, ui_followup_flow)",
    )
    parser.add_argument(
        "--baseline-model",
        default="",
        help="hosted/frontier model id for a head-to-head run (e.g. grok-4.7)",
    )
    parser.add_argument(
        "--baseline-url",
        default="",
        help="OpenAI-compatible baseline base URL (default: OpenCode Zen)",
    )
    parser.add_argument(
        "--baseline-key-env",
        default="",
        help="Optional environment variable holding the hosted API key",
    )
    args = parser.parse_args(argv)

    only = [item for item in args.only.split(",") if item.strip()]
    if args.baseline_model:
        baseline_key = os.environ.get(args.baseline_key_env, "") if args.baseline_key_env else ""
        payload = run_comparison(
            args.model,
            args.url,
            args.baseline_model,
            args.baseline_url,
            only=only,
            baseline_api_key=baseline_key,
        )
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
        print(
            f"\nlocal {payload['local_score']:.0%} vs "
            f"baseline {payload['baseline_score']:.0%} "
            f"({payload['winner']}, Δ{payload['score_delta']:+.0%})"
        )
        return 0 if payload["local_score"] >= payload["local"]["target"] else 1

    report = run_benchmark(args.mode, args.model, args.url, only=only)
    payload = report.to_dict()
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(
        f"\n{report.passed}/{report.total} scenarios passed "
        f"(score {report.score:.0%}, target {report.target:.0%})"
    )
    return 0 if payload["meets_target"] else 1


if __name__ == "__main__":  # pragma: no cover - exercised through the script
    sys.exit(main())
