from __future__ import annotations

from pathlib import Path
from typing import Any


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
