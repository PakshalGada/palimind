#!/usr/bin/env python3
"""Live probe: does capability routing actually pick the frontier fallback?

Run once with routing off and once with a configured frontier model, then
compare latency and answer quality::

    PALIMIND_AGENT_MODEL_ROUTING=off \
      python scripts/routing_live_probe.py --json /tmp/routing-local.json

    PALIMIND_AGENT_MODEL_ROUTING=auto PALIMIND_FRONTIER_MODELS=grok-4.7 \
      python scripts/routing_live_probe.py --json /tmp/routing-frontier.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "packages" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

TASK = (
    "A service handles 1,200 requests per second. A cache removes 38% of "
    "backend calls, and each backend call consumes 7 ms of CPU. Compute the "
    "CPU milliseconds per second saved and finish with SAVED=<number>."
)
EXPECTED = "3192"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live capability-routing probe")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--routing", choices=("off", "local", "auto", "frontier"), default="")
    parser.add_argument("--frontier", default="")
    parser.add_argument("--task", default=TASK)
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)

    if args.routing:
        os.environ["PALIMIND_AGENT_MODEL_ROUTING"] = args.routing
    if args.frontier:
        os.environ["PALIMIND_FRONTIER_MODELS"] = args.frontier
    # The probe measures the main answer, not follow-up generation.
    os.environ.setdefault("PALIMIND_AGENT_FOLLOWUPS", "0")

    import asyncio

    from palimind.agents.catalog import AgentDefinition
    from palimind.agents.runtime import run_with_definition

    defn = AgentDefinition.new(
        "routing-probe",
        display_name="Routing Probe",
        model=args.model,
        tools=["todo_write"],
        max_iterations=8,
        reasoning_effort="high",
        planning_mode="off",
        self_critique=False,
        autonomy_level="off",
        memory_mode="off",
    )
    events: list[tuple[str, dict]] = []

    async def emit(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    started = time.time()
    with tempfile.TemporaryDirectory(prefix="palimind-routing-probe-") as tmp:
        output = asyncio.run(
            run_with_definition(
                defn,
                args.task,
                emit=emit,
                calling_root=Path(tmp),
                interactive=False,
            )
        )
    elapsed = time.time() - started
    route = next((payload for kind, payload in events if kind == "agent:model_route"), {})
    result = {
        "requested_model": args.model,
        "routing_mode": os.environ.get("PALIMIND_AGENT_MODEL_ROUTING", "auto"),
        "frontier_models": os.environ.get("PALIMIND_FRONTIER_MODELS", ""),
        "route": route,
        "elapsed_s": round(elapsed, 2),
        "quality_pass": EXPECTED in output,
        "answer_chars": len(output),
        "answer": output[:1200],
    }
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["quality_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
