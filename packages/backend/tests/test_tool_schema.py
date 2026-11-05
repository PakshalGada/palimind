"""Tests for typed tool contracts (JSON Schema + argument coercion)."""

from __future__ import annotations

from palimind.agents.tools.base import (
    coerce_tool_args,
    normalize_parameters,
    parameters_to_schema,
)
from palimind.llm.mixture_of_expert.llm import ollama_tools_from_registry


def test_legacy_parameters_become_required_strings() -> None:
    schema = parameters_to_schema(
        {
            "query": "The search query",
            "max_results": "Optional: maximum results (default 5)",
        }
    )
    assert schema["type"] == "object"
    assert schema["properties"]["query"] == {
        "type": "string",
        "description": "The search query",
    }
    assert schema["properties"]["max_results"]["type"] == "string"
    assert schema["required"] == ["query"]


def test_typed_parameters_keep_types_enums_and_defaults() -> None:
    schema = parameters_to_schema(
        {
            "limit": {"type": "integer", "description": "Max", "default": 5},
            "deep": {"type": "boolean", "description": "Deep mode", "default": False},
            "mode": {
                "type": "string",
                "description": "Mode",
                "enum": ["fast", "deep"],
                "default": "fast",
            },
            "tags": {
                "type": "array",
                "description": "Tags",
                "items": {"type": "string"},
            },
            "filters": {"type": "object", "description": "Filters"},
        }
    )
    props = schema["properties"]
    assert props["limit"]["type"] == "integer"
    assert props["deep"]["type"] == "boolean"
    assert props["mode"]["enum"] == ["fast", "deep"]
    assert props["tags"]["type"] == "array"
    assert props["tags"]["items"] == {"type": "string"}
    assert props["filters"]["type"] == "object"
    # Only parameters without a default are required.
    assert schema["required"] == ["tags", "filters"]


def test_object_schema_passthrough() -> None:
    raw = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
    }
    assert parameters_to_schema(raw) == raw


def test_coerce_integer_boolean_array_and_object() -> None:
    params = {
        "limit": {"type": "integer"},
        "deep": {"type": "boolean"},
        "tags": {"type": "array"},
        "filters": {"type": "object"},
        "query": {"type": "string"},
    }
    args, error = coerce_tool_args(
        "demo",
        params,
        {
            "limit": "5",
            "deep": "true",
            "tags": '["a", "b"]',
            "filters": '{"year": 2025}',
            "query": 42,
        },
    )
    assert error is None
    assert args == {
        "limit": 5,
        "deep": True,
        "tags": ["a", "b"],
        "filters": {"year": 2025},
        "query": "42",
    }


def test_coerce_reports_precise_errors() -> None:
    params = {
        "limit": {"type": "integer"},
        "mode": {"type": "string", "enum": ["fast", "deep"]},
    }

    args, error = coerce_tool_args("demo", params, {"limit": "many"})
    assert args is not None and error is not None
    assert "'limit' must be an integer" in error

    _args, error = coerce_tool_args("demo", params, {"limit": 1, "mode": "sideways"})
    assert error is not None and "must be one of" in error

    _args, error = coerce_tool_args("demo", params, {})
    assert error is not None and "'limit' is required" in error


def test_ollama_schema_uses_real_types() -> None:
    tools = ollama_tools_from_registry(
        {
            "demo": {
                "description": "Demo",
                "parameters": {
                    "count": {"type": "integer", "description": "Count"},
                    "flag": {"type": "boolean", "description": "Flag", "default": False},
                },
            }
        }
    )
    schema = tools[0]["function"]["parameters"]
    assert schema["properties"]["count"]["type"] == "integer"
    assert schema["properties"]["flag"]["type"] == "boolean"
    assert schema["required"] == ["count"]


def test_registry_core_tools_are_typed() -> None:
    from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY

    schema = parameters_to_schema(TOOL_REGISTRY["web_search"]["parameters"])
    assert schema["properties"]["max_results"]["type"] == "integer"
    assert schema["properties"]["query"]["type"] == "string"
    assert TOOL_REGISTRY["read_file"]["parallel_safe"] is True
    assert TOOL_REGISTRY["write_file"]["parallel_safe"] is False


def test_coerce_accepts_full_object_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "Max"}},
        "required": ["limit"],
    }
    args, error = coerce_tool_args("demo", schema, {"limit": "3"})
    assert error is None
    assert args["limit"] == 3
    _args, error = coerce_tool_args("demo", schema, {})
    assert error is not None and "'limit' is required" in error


def test_normalize_parameters_accepts_parameter_instances() -> None:
    from palimind.agents.tools.base import ToolParam

    params = normalize_parameters({"x": ToolParam(name="x", type="number")})
    assert params[0].type == "number"
