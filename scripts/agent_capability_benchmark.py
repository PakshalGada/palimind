#!/usr/bin/env python3
"""Run the PaliMind agent capability benchmark.

Examples:
    python scripts/agent_capability_benchmark.py                  # deterministic
    python scripts/agent_capability_benchmark.py --mode live \
        --model qwen3.5:9b --json benchmarks/agent-capability-live.json
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "packages" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from palimind.agents.capability_benchmark import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
