"""Core abstractions for in-app agent tools.

A "tool" is a capability an agent can invoke (web search, shell exec, ...).
Tools live inside the agents folder at ``palimind/agents/tools/<name>/`` and
are discovered via a ``tool.json`` manifest. See skills/agent-tools.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Permission names a tool may request in its manifest.
PERMISSIONS = ("network", "fs-read", "fs-write", "shell")


@dataclass
class ToolContext:
    """Everything a tool may need at run time.

    Attributes:
        workspace_root: Active workspace directory (sandbox boundary).
        allowed_paths: Extra absolute paths the tool may touch.
        settings: Mapping of PALIMIND_* setting values for overrides.
    """

    workspace_root: Path | None = None
    allowed_paths: list[Path] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Uniform return type for every tool invocation."""

    ok: bool
    output: str
    error: str | None = None

    def __str__(self) -> str:  # agents consume text
        if self.ok:
            return self.output
        return f"Error: {self.error or self.output}"


class Tool(ABC):
    """Base class every agent tool implements."""

    #: unique slug, must match the manifest folder name
    name: str = ""
    description: str = ""
    permissions: tuple[str, ...] = ()
    timeout_s: int = 30

    @abstractmethod
    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute the tool."""


class FunctionTool(Tool):
    """Adapts a plain callable (legacy tool functions) to the Tool contract."""

    def __init__(
        self,
        func: Callable[..., str],
        name: str,
        description: str,
        permissions: tuple[str, ...] = (),
        timeout_s: int = 30,
    ):
        self._func = func
        self.name = name
        self.description = description
        self.permissions = permissions
        self.timeout_s = timeout_s

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        from palimind.agents.tools.sandbox import run_sandboxed

        sig = inspect.signature(self._func)
        kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
        try:
            output = await run_sandboxed(
                lambda: self._func(**kwargs),
                timeout_s=self.timeout_s,
                tool_name=self.name,
            )
        except Exception as exc:  # noqa: BLE001 - tools must never crash agents
            return ToolResult(ok=False, output="", error=str(exc))
        ok = not output.lower().startswith("error")
        return ToolResult(ok=ok, output=output, error=None if ok else output)
