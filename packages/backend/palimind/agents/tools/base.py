"""Core abstractions for in-app agent tools.

A "tool" is a capability an agent can invoke (web search, shell exec, ...).
Tools live inside the agents folder at ``palimind/agents/tools/<name>/`` and
are discovered via a ``tool.json`` manifest. See skills/agent-tools.

Tool parameters may be declared in two forms:

Legacy (still supported)::

    "parameters": {
        "query": "The search query",
        "limit": "Optional: maximum results (default 5)",
    }

Typed (preferred)::

    "parameters": {
        "query": {"type": "string", "description": "The search query"},
        "limit": {"type": "integer", "description": "Maximum results", "default": 5},
        "mode":  {"type": "string", "enum": ["fast", "deep"], "default": "fast"},
    }

Typed declarations let the model emit correct JSON types (integers, booleans,
arrays, enums) instead of everything being a string.  Both forms are
normalized to JSON Schema by :func:`parameters_to_schema` and validated by
:func:`coerce_tool_args`.
"""

from __future__ import annotations

import inspect
import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Permission names a tool may request in its manifest.
PERMISSIONS = ("network", "fs-read", "fs-write", "shell", "os", "secrets")

ParamType = Literal["string", "integer", "number", "boolean", "array", "object"]
_PARAM_TYPES: tuple[str, ...] = ("string", "integer", "number", "boolean", "array", "object")

# JSON Schema scalar type accepted for each declared type.  ``integer`` is a
# subset of ``number``; validation below handles that explicitly.
_JSON_TYPES: dict[str, str] = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
}


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


@dataclass(frozen=True)
class ToolParam:
    """One typed tool parameter.

    ``required`` defaults to True for typed declarations; a parameter with a
    ``default`` is treated as optional unless it explicitly says otherwise.
    """

    name: str
    type: ParamType = "string"
    description: str = ""
    required: bool = True
    enum: tuple[str, ...] = ()
    default: Any = None
    items: Mapping[str, Any] | None = None
    minimum: float | None = None
    maximum: float | None = None

    def to_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {
            "type": _JSON_TYPES.get(self.type, "string"),
            "description": self.description or self.name,
        }
        if self.enum:
            schema["enum"] = list(self.enum)
        if self.default is not None:
            schema["default"] = self.default
        if self.type == "array" and self.items:
            schema["items"] = dict(self.items)
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        return schema


@dataclass(frozen=True)
class ToolSpec:
    """Complete, typed description of a tool for the model and the UI."""

    name: str
    description: str
    params: tuple[ToolParam, ...] = ()
    permissions: tuple[str, ...] = ()
    tier: int = 1
    requires_approval: bool = False
    timeout_s: int = 30
    parallel_safe: bool = False
    idempotent: bool = False
    returns: str = "text"

    def to_schema(self) -> dict[str, Any]:
        properties = {p.name: p.to_schema() for p in self.params}
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        required = [p.name for p in self.params if p.required and p.default is None]
        if required:
            schema["required"] = required
        return schema

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.to_schema(),
            "permissions": list(self.permissions),
            "tier": self.tier,
            "requires_approval": self.requires_approval,
            "timeout_s": self.timeout_s,
            "parallel_safe": self.parallel_safe,
            "idempotent": self.idempotent,
            "returns": self.returns,
        }


def _legacy_param(name: str, description: str) -> ToolParam:
    """Convert the old ``"name": "description"`` form to a typed param."""
    desc = str(description or "")
    lowered = desc.lower()
    optional = lowered.startswith("optional") or "default" in lowered
    return ToolParam(name=name, type="string", description=desc, required=not optional)


def normalize_parameters(raw: Mapping[str, Any] | None) -> tuple[ToolParam, ...]:
    """Normalize legacy and typed parameter declarations to ``ToolParam`` objects."""
    if not raw:
        return ()
    params: list[ToolParam] = []
    for name, spec in raw.items():
        key = str(name)
        if isinstance(spec, ToolParam):
            params.append(spec)
            continue
        if isinstance(spec, str):
            params.append(_legacy_param(key, spec))
            continue
        if not isinstance(spec, Mapping):
            params.append(_legacy_param(key, str(spec)))
            continue

        ptype = str(spec.get("type") or "string").lower()
        if ptype not in _PARAM_TYPES:
            ptype = "string"
        raw_enum = spec.get("enum") or ()
        if isinstance(raw_enum, str):
            raw_enum = (raw_enum,)
        raw_default = spec.get("default")
        required = spec.get("required")
        if required is None:
            required = raw_default is None
        elif isinstance(required, str):
            required = required.strip().lower() not in ("0", "false", "no", "off")
        items = spec.get("items")
        params.append(
            ToolParam(
                name=key,
                type=ptype,  # type: ignore[arg-type]
                description=str(spec.get("description") or key),
                required=bool(required) and raw_default is None,
                enum=tuple(str(v) for v in raw_enum),
                default=raw_default,
                items=dict(items) if isinstance(items, Mapping) else None,
                minimum=float(spec["minimum"]) if spec.get("minimum") is not None else None,
                maximum=float(spec["maximum"]) if spec.get("maximum") is not None else None,
            )
        )
    return tuple(params)


def parameters_to_schema(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return an object JSON Schema for a tool's parameter declarations.

    Accepts the legacy/typed parameter map or an already-built JSON Schema
    object (``{"type": "object", "properties": {...}}``) and returns a copy.
    """
    if isinstance(raw, Mapping) and raw.get("type") == "object" and "properties" in raw:
        return dict(raw)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in normalize_parameters(raw):
        properties[param.name] = param.to_schema()
        if param.required and param.default is None:
            required.append(param.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _coerce_scalar(name: str, value: Any, ptype: str) -> tuple[Any, str | None]:
    """Coerce one value to *ptype*; return ``(value, error)``."""
    if ptype == "string":
        if isinstance(value, str):
            return value, None
        if isinstance(value, (int, float, bool)):
            return str(value), None
        return value, f"'{name}' must be a string"
    if ptype == "integer":
        if isinstance(value, bool):
            return value, f"'{name}' must be an integer, got a boolean"
        if isinstance(value, int):
            return value, None
        if isinstance(value, float) and value.is_integer():
            return int(value), None
        if isinstance(value, str):
            try:
                return int(value.strip()), None
            except ValueError:
                return value, f"'{name}' must be an integer, got {value!r}"
        return value, f"'{name}' must be an integer, got {value!r}"
    if ptype == "number":
        if isinstance(value, bool):
            return value, f"'{name}' must be a number, got a boolean"
        if isinstance(value, (int, float)):
            return float(value), None
        if isinstance(value, str):
            try:
                return float(value.strip()), None
            except ValueError:
                return value, f"'{name}' must be a number, got {value!r}"
        return value, f"'{name}' must be a number, got {value!r}"
    if ptype == "boolean":
        if isinstance(value, bool):
            return value, None
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes", "on"):
                return True, None
            if lowered in ("false", "0", "no", "off"):
                return False, None
        return value, f"'{name}' must be a boolean, got {value!r}"
    if ptype == "array":
        if isinstance(value, (list, tuple)):
            return list(value), None
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return [], None
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return value, f"'{name}' must be a JSON array or list, got {value!r}"
            if isinstance(parsed, list):
                return parsed, None
        return value, f"'{name}' must be an array, got {value!r}"
    if ptype == "object":
        if isinstance(value, Mapping):
            return dict(value), None
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return value, f"'{name}' must be a JSON object or mapping, got {value!r}"
            if isinstance(parsed, Mapping):
                return dict(parsed), None
        return value, f"'{name}' must be an object, got {value!r}"
    return value, None


def coerce_tool_args(
    tool_name: str,
    raw_parameters: Mapping[str, Any] | None,
    args: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], str | None]:
    """Validate and coerce tool arguments against their declared schema.

    Returns ``(coerced_args, error)``.  ``error`` is a model-readable message
    (not an exception) so the agent loop can retry with corrected arguments.
    Unknown arguments are preserved: ``inspect.signature.bind`` still rejects
    genuinely invalid calls, and keeping them avoids breaking tools that accept
    ``**kwargs``.
    """
    data = dict(args or {})
    params = normalize_parameters(raw_parameters)
    if (
        isinstance(raw_parameters, Mapping)
        and raw_parameters.get("type") == "object"
        and isinstance(raw_parameters.get("properties"), Mapping)
    ):
        required = {str(x) for x in (raw_parameters.get("required") or [])}
        converted: dict[str, Any] = {}
        for pname, spec in raw_parameters["properties"].items():
            if isinstance(spec, Mapping):
                item = dict(spec)
                item.setdefault("required", str(pname) in required)
                converted[str(pname)] = item
        params = normalize_parameters(converted)
    if not params:
        return data, None

    for param in params:
        value = data.get(param.name)
        if value is None:
            if param.required and param.default is None:
                return data, f"Tool '{tool_name}' argument error: '{param.name}' is required"
            if param.default is not None:
                data[param.name] = param.default
            continue

        coerced, err = _coerce_scalar(param.name, value, param.type)
        if err:
            return data, f"Tool '{tool_name}' argument error: {err}"
        if param.enum and str(coerced) not in param.enum:
            allowed = ", ".join(param.enum)
            return data, (
                f"Tool '{tool_name}' argument error: '{param.name}' must be one of "
                f"[{allowed}], got {coerced!r}"
            )
        if param.minimum is not None and float(coerced) < param.minimum:
            return data, (
                f"Tool '{tool_name}' argument error: '{param.name}' must be >= "
                f"{param.minimum}, got {coerced!r}"
            )
        if param.maximum is not None and float(coerced) > param.maximum:
            return data, (
                f"Tool '{tool_name}' argument error: '{param.name}' must be <= "
                f"{param.maximum}, got {coerced!r}"
            )
        data[param.name] = coerced
    return data, None


def tool_spec_from_manifest(
    name: str,
    description: str,
    raw_parameters: Mapping[str, Any] | None,
    *,
    permissions: tuple[str, ...] = (),
    tier: int = 1,
    requires_approval: bool = False,
    timeout_s: int = 30,
    parallel_safe: bool = False,
    idempotent: bool = False,
    returns: str = "text",
) -> ToolSpec:
    """Build a :class:`ToolSpec` from a manifest/TOOL_DEFINITION payload."""
    return ToolSpec(
        name=name,
        description=description,
        params=normalize_parameters(raw_parameters),
        permissions=permissions,
        tier=int(tier or 1),
        requires_approval=bool(requires_approval),
        timeout_s=int(timeout_s or 30),
        parallel_safe=bool(parallel_safe),
        idempotent=bool(idempotent),
        returns=str(returns or "text"),
    )


class Tool(ABC):
    """Base class every agent tool implements."""

    #: unique slug, must match the manifest folder name
    name: str = ""
    description: str = ""
    permissions: tuple[str, ...] = ()
    timeout_s: int = 30
    #: parameters declared in the manifest/TOOL_DEFINITION form.
    parameters: Mapping[str, Any] = {}
    tier: int = 1
    requires_approval: bool = False
    #: safe to run concurrently with other ``parallel_safe`` tools.
    parallel_safe: bool = False
    #: safe to replay on resume (no externally visible side effects).
    idempotent: bool = False
    #: where the tool came from: builtin | user | workspace.
    source: str = "builtin"

    @abstractmethod
    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute the tool."""

    def spec(self) -> ToolSpec:
        return tool_spec_from_manifest(
            self.name,
            self.description,
            self.parameters,
            permissions=self.permissions,
            tier=self.tier,
            requires_approval=self.requires_approval,
            timeout_s=self.timeout_s,
            parallel_safe=self.parallel_safe,
            idempotent=self.idempotent,
        )


class FunctionTool(Tool):
    """Adapts a plain callable (legacy tool functions) to the Tool contract."""

    def __init__(
        self,
        func: Callable[..., str],
        name: str,
        description: str,
        permissions: tuple[str, ...] = (),
        timeout_s: int = 30,
        parameters: Mapping[str, Any] | None = None,
        tier: int = 1,
        requires_approval: bool = False,
        parallel_safe: bool = False,
        idempotent: bool = False,
    ):
        self._func = func
        self.name = name
        self.description = description
        self.permissions = permissions
        self.timeout_s = timeout_s
        self.parameters = dict(parameters or {})
        self.tier = int(tier or 1)
        self.requires_approval = bool(requires_approval)
        self.parallel_safe = bool(parallel_safe)
        self.idempotent = bool(idempotent)

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
