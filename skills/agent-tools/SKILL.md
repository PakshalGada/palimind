---
name: palimind-agent-tools
description: >
  How to author, register, and modify in-app agent tools under
  packages/backend/palimind/agents/tools. REQUIRED when adding a new agent
  capability or editing existing tools. Triggers: tool, registry, sandbox,
  permissions, run_shell, web search, agent capability.
---

# Authoring In-App Agent Tools

In-app agent tools are the capabilities Palimind's own agents can invoke
(shell exec, web search, CSV query…). They live **inside the agents folder**:
`packages/backend/palimind/agents/tools/`.

Do not confuse them with `/skills` at the repo root — those are developer
skills (SKILL.md) for AI coding agents and are never shipped in the app.

## Adding a new tool

1. Create a folder: `agents/tools/my-tool/`
2. Add `tool.json` manifest:

```json
{
  "name": "my-tool",
  "version": "1.0.0",
  "description": "One line describing what it does",
  "entrypoint": "tool.py",
  "permissions": ["network"],
  "timeout_s": 30
}
```

3. Add `tool.py` implementing the Tool contract:

```python
from palimind.agents.tools.base import Tool, ToolContext, ToolResult

class MyTool(Tool):
    name = "my-tool"

    async def run(self, ctx: ToolContext, **kwargs) -> ToolResult:
        ...
```

4. Register it via `palimind.agents.tools.registry` (auto-discovers folders).
5. Add tests; `pm tools doctor my-tool` must pass.

## Rules

- Declare the MINIMUM permissions needed: `network`, `fs-read`, `fs-write`,
  `shell`. Anything touching the filesystem must respect
  `PALIMIND_ALLOWED_PATHS` + workspace root.
- All execution goes through the sandbox (`sandbox.py`) — timeouts, output
  caps, audit logging. Never bypass it.
- Tools must degrade gracefully when their optional dependencies are missing
  (see browse_url_tool's playwright guard for the pattern).
- Audit logging is mandatory — reuse the existing audit helpers.
