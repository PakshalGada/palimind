"""In-app agent tools.

Every capability an agent can invoke lives here as ``<slug>/tool.json`` +
``<slug>/tool.py``. Discovery is handled by :mod:`.registry`; execution
limits by :mod:`.sandbox`. See skills/agent-tools (repo root) before adding
a new tool.
"""

from palimind.agents.tools.base import FunctionTool, Tool, ToolContext, ToolResult
from palimind.agents.tools.registry import discover_tools, get_registry, get_tool, list_tools

__all__ = [
    "FunctionTool",
    "Tool",
    "ToolContext",
    "ToolResult",
    "discover_tools",
    "get_registry",
    "get_tool",
    "list_tools",
]
