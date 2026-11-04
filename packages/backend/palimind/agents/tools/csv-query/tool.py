from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

# ``DataFrame.query`` evaluates its string: ``@name`` reaches the caller's
# locals (``@pd.io.common.os.system(...)`` runs a host command) and method
# calls reach ``to_csv``/``to_pickle``. Only plain filter expressions over
# columns are accepted, with a small set of side-effect-free methods.
_SAFE_METHODS = frozenset(
    {
        "str", "dt", "contains", "startswith", "endswith", "match", "fullmatch",
        "lower", "upper", "strip", "len", "isin", "between", "isna", "notna",
        "isnull", "notnull", "abs", "round", "year", "month", "day",
    }
)  # fmt: skip
_SAFE_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub,
    ast.UAdd, ast.Invert, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.FloorDiv, ast.Mod, ast.Pow, ast.BitAnd, ast.BitOr, ast.Compare, ast.Eq,
    ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is,
    ast.IsNot, ast.Name, ast.Load, ast.Constant, ast.List, ast.Tuple,
    ast.Attribute, ast.Call, ast.keyword,
)  # fmt: skip


def _unsafe_query(query: str) -> str | None:
    """Return why *query* is not a plain filter expression, else None."""
    # Backtick-quoted column names may contain anything; mask them.
    masked = re.sub(r"`[^`]*`", "_col", query)
    try:
        tree = ast.parse(masked.strip(), mode="eval")
    except SyntaxError:
        return "not a valid filter expression ('@' variables are not allowed)"
    for node in ast.walk(tree):
        if not isinstance(node, _SAFE_NODES):
            return f"'{type(node).__name__}' is not allowed"
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            return f"name '{node.id}' is not allowed"
        if isinstance(node, ast.Attribute) and node.attr not in _SAFE_METHODS:
            return f"attribute '{node.attr}' is not allowed"
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Attribute):
            return "only column methods such as .str.contains() may be called"
    return None


def csv_query(file_path: str, query: str = "") -> str:
    """Run a pandas query against a CSV file within the field's allowed
    paths. Returns matching rows as a JSON list of dicts (truncated)."""
    from palimind.llm.mixture_of_expert.tools import _get_context, _resolve_in_workspace

    ctx = _get_context()
    root: Path | None = ctx.get("root")
    if root is None:
        return "Error: no active workspace configured for CSV queries."

    resolved = _resolve_in_workspace(file_path)
    if resolved is None:
        return f"Error: access denied — '{file_path}' is outside the workspace"
    if not resolved.exists() or not resolved.is_file():
        return f"Error: file not found at {file_path}"
    if resolved.suffix.lower() != ".csv":
        return f"Error: '{file_path}' is not a CSV file"

    import pandas as pd

    try:
        df = pd.read_csv(resolved)
    except Exception as e:
        return f"Error reading CSV: {e}"

    if df.empty:
        return "[]"

    if query:
        reason = _unsafe_query(str(query))
        if reason:
            return f"Error in pandas query: {reason}"
        try:
            df = df.query(query)
        except Exception as e:
            return f"Error in pandas query: {e}"

    if df.empty:
        return "[]"

    records = df.head(200).to_dict(orient="records")
    import json

    return json.dumps(records, default=str, ensure_ascii=False)


# registry metadata for the main TOOL_REGISTRY
TOOL_DEFINITION: dict[str, Any] = {
    "description": (
        "Query a CSV file inside the field workspace using a pandas query "
        'string (e.g. "amount > 100"). Returns matching rows as JSON.'
    ),
    "parameters": {
        "file_path": "Path to the CSV file (workspace-relative or absolute)",
        "query": "Optional: pandas query string to filter rows",
    },
    "tier": 1,
    "requires_approval": False,
}
