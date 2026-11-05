"""Data tools: DuckDB analytics, spreadsheet read/write and charts.

All inputs/outputs are resolved through the workspace sandbox. Read tools are
tier 1; tools that create files are tier 2 and require approval.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_FORBIDDEN_SQL = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "copy",
    "attach",
    "detach",
    "install",
    "load",
    "pragma",
    "export",
    "import",
    "call",
    "vacuum",
)


def _resolve(path: str, *, write: bool = False) -> Path | None:
    from palimind.llm.mixture_of_expert.tools import _resolve_in_workspace

    return _resolve_in_workspace(str(path), write=write)


def _rel(path: Path) -> str:
    from palimind.llm.mixture_of_expert.tools import _workspace_root

    root = _workspace_root()
    try:
        return str(path.relative_to(root)) if root else str(path)
    except Exception:
        return str(path)


def _source_reader(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".parquet", ".pq"):
        return "read_parquet"
    if suffix in (".json", ".jsonl", ".ndjson"):
        return "read_json_auto"
    return "read_csv_auto"


def duckdb_query(
    query: str,
    source: str = "",
    params: Any = None,
    max_rows: int = 200,
) -> str:
    """Run a read-only DuckDB query over ``data`` (a workspace CSV/Parquet/JSON)."""
    sql = str(query or "").strip()
    if not sql:
        return "Error: query is required"
    lowered = sql.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return "Error: only SELECT/CTE queries are allowed"
    stripped = lowered.rstrip(";")
    if ";" in stripped:
        return "Error: multiple SQL statements are not allowed"
    for word in _FORBIDDEN_SQL:
        if word in lowered.split():
            return f"Error: {word.upper()} is not allowed in a read-only query"
    try:
        import duckdb

        conn = duckdb.connect(":memory:")
        try:
            if source:
                src = _resolve(source)
                if src is None:
                    return f"Error: access denied — '{source}' is outside the workspace"
                if not src.is_file():
                    return f"Error: data source not found: {source}"
                escaped = str(src).replace("'", "''")
                reader = _source_reader(src)
                conn.execute(f"CREATE VIEW data AS SELECT * FROM {reader}('{escaped}')")
            bound = params if isinstance(params, list) else []
            cursor = conn.execute(sql, bound)
            columns = [d[0] for d in (cursor.description or [])]
            limit = max(1, min(int(max_rows or 200), 2000))
            rows = cursor.fetchmany(limit + 1)
            truncated = len(rows) > limit
            rows = rows[:limit]
            payload = {
                "columns": columns,
                "rows": [list(row) for row in rows],
                "row_count": len(rows),
                "truncated": truncated,
            }
            return json.dumps(payload, default=str, ensure_ascii=False)
        finally:
            conn.close()
    except ImportError:
        return "Error: duckdb is not installed (`pip install duckdb`)."
    except Exception as exc:  # noqa: BLE001
        return f"Error running DuckDB query: {exc}"


def xlsx_read(path: str, sheet: str = "", max_rows: int = 200) -> str:
    """Read an Excel workbook sheet as JSON rows."""
    target = _resolve(path)
    if target is None or not target.is_file():
        return f"Error: workbook not found: {path}"
    try:
        from openpyxl import load_workbook

        wb = load_workbook(str(target), read_only=True, data_only=True)
        try:
            names = list(wb.sheetnames)
            chosen = sheet if sheet in names else (names[0] if names else "")
            if not chosen:
                return "Error: workbook has no sheets"
            ws = wb[chosen]
            limit = max(1, min(int(max_rows or 200), 2000))
            rows: list[list[Any]] = []
            for index, row in enumerate(ws.iter_rows(values_only=True)):
                if index >= limit:
                    break
                rows.append(list(row))
            return json.dumps(
                {"sheet": chosen, "sheets": names, "rows": rows, "row_count": len(rows)},
                default=str,
                ensure_ascii=False,
            )
        finally:
            wb.close()
    except Exception as exc:  # noqa: BLE001
        return f"Error reading XLSX: {exc}"


def _normalise_sheets(
    sheets: Any, rows: Any = None, sheet_name: str = "Sheet1"
) -> list[dict[str, Any]]:
    if isinstance(sheets, str):
        try:
            sheets = json.loads(sheets)
        except json.JSONDecodeError:
            sheets = None
    if not sheets and rows is not None:
        sheets = [{"name": sheet_name, "rows": rows}]
    if isinstance(sheets, dict):
        sheets = [{"name": k, "rows": v} for k, v in sheets.items()]
    if not isinstance(sheets, list):
        return []
    out: list[dict[str, Any]] = []
    for item in sheets:
        if isinstance(item, dict):
            out.append(
                {
                    "name": str(item.get("name") or f"Sheet{len(out) + 1}")[:31],
                    "rows": item.get("rows") or [],
                }
            )
    return out


def xlsx_write(path: str, sheets: Any, rows: Any = None, sheet_name: str = "Sheet1") -> str:
    """Create or overwrite an Excel workbook from sheet/row data."""
    target = _resolve(path, write=True)
    if target is None:
        return f"Error: access denied — '{path}' is outside the workspace"
    data = _normalise_sheets(sheets, rows, sheet_name)
    if not data:
        return "Error: sheets must be a non-empty list of {name, rows}"
    try:
        from openpyxl import Workbook

        wb = Workbook()
        wb.remove(wb.active)
        for sheet in data:
            ws = wb.create_sheet(title=sheet["name"] or "Sheet")
            for row in sheet["rows"]:
                values = row if isinstance(row, (list, tuple)) else [row]
                ws.append(list(values))
        target.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(target))
        return f"Wrote {len(data)} sheet(s) to {_rel(target)}"
    except Exception as exc:  # noqa: BLE001
        return f"Error writing XLSX: {exc}"


def _load_frame(path: Path):
    import pandas as pd

    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(path)
    if suffix in (".json", ".jsonl", ".ndjson"):
        return pd.read_json(path)
    return pd.read_csv(path)


def chart_generate(
    source: str,
    output: str = "chart.png",
    chart_type: str = "line",
    title: str = "",
    x_column: str = "",
    y_columns: Any = None,
    max_rows: int = 5000,
) -> str:
    """Generate a PNG chart from a workspace CSV/XLSX/JSON file."""
    src = _resolve(source)
    target = _resolve(output, write=True)
    if src is None:
        return f"Error: access denied — '{source}' is outside the workspace"
    if not src.is_file():
        return f"Error: data source not found: {source}"
    if target is None:
        return f"Error: access denied — '{output}' is outside the workspace"
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        df = _load_frame(src)
        if len(df) > max_rows:
            df = df.head(max_rows)
        if x_column and x_column in df.columns:
            x = df[x_column]
        else:
            x = df.index
        if isinstance(y_columns, str):
            y_columns = [c.strip() for c in y_columns.split(",") if c.strip()]
        if not isinstance(y_columns, list) or not y_columns:
            y_columns = [
                c
                for c in df.columns
                if c != x_column and str(df[c].dtype).startswith(("int", "float"))
            ]
        y_columns = [c for c in y_columns if c in df.columns]
        if not y_columns:
            return "Error: no numeric columns to chart"
        fig, ax = plt.subplots(figsize=(9, 5))
        kind = str(chart_type or "line").lower()
        for column in y_columns:
            if kind == "bar":
                ax.bar(x, df[column], label=str(column))
            elif kind == "scatter":
                ax.scatter(x, df[column], label=str(column))
            else:
                ax.plot(x, df[column], label=str(column))
        if title:
            ax.set_title(title)
        ax.legend()
        fig.tight_layout()
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(target), dpi=120)
        plt.close(fig)
        size = target.stat().st_size
        return (
            f"Generated {kind} chart with {len(y_columns)} series at {_rel(target)} ({size} bytes)"
        )
    except Exception as exc:  # noqa: BLE001
        return f"Error generating chart: {exc}"


def _p(
    *,
    type: str = "string",
    description: str,
    required: bool = True,
    default: Any = None,
    items: dict[str, Any] | None = None,
    enum: tuple[str, ...] = (),
) -> dict[str, Any]:
    spec: dict[str, Any] = {"type": type, "description": description, "required": required}
    if default is not None:
        spec["default"] = default
        spec["required"] = False
    if items:
        spec["items"] = items
    if enum:
        spec["enum"] = list(enum)
    return spec


TOOLS: dict[str, dict[str, Any]] = {
    "duckdb_query": {
        "fn": duckdb_query,
        "description": (
            "Run a read-only DuckDB SQL query. Use source=<CSV/Parquet/JSON in the "
            "workspace> and query the view named 'data'."
        ),
        "parameters": {
            "query": _p(description="SELECT/CTE SQL query (view: data)"),
            "source": _p(
                description="Workspace CSV/Parquet/JSON file to expose as 'data'",
                required=False,
            ),
            "params": _p(
                type="array",
                description="Bound parameter values",
                required=False,
                items={"type": ["string", "number", "boolean", "null"]},
            ),
            "max_rows": _p(type="integer", description="Maximum rows", default=200),
        },
        "tier": 1,
        "requires_approval": False,
        "parallel_safe": True,
        "idempotent": True,
    },
    "xlsx_read": {
        "fn": xlsx_read,
        "description": "Read an Excel workbook sheet as JSON rows.",
        "parameters": {
            "path": _p(description="Workspace-relative XLSX path"),
            "sheet": _p(description="Sheet name (default first sheet)", required=False),
            "max_rows": _p(type="integer", description="Maximum rows", default=200),
        },
        "tier": 1,
        "requires_approval": False,
        "parallel_safe": True,
        "idempotent": True,
    },
    "xlsx_write": {
        "fn": xlsx_write,
        "description": "Create or overwrite an Excel workbook from sheet/row data.",
        "parameters": {
            "path": _p(description="Output XLSX path"),
            "sheets": _p(
                type="array",
                description='List of {"name": "...", "rows": [[...]]} objects',
                items={"type": "object"},
            ),
            "sheet_name": _p(description="Fallback sheet name", default="Sheet1"),
        },
        "tier": 2,
        "requires_approval": True,
        "parallel_safe": False,
        "idempotent": False,
    },
    "chart_generate": {
        "fn": chart_generate,
        "description": "Generate a PNG line/bar/scatter chart from a workspace data file.",
        "parameters": {
            "source": _p(description="CSV/XLSX/JSON data file"),
            "output": _p(description="Output PNG path", default="chart.png"),
            "chart_type": _p(
                type="string",
                description="line, bar or scatter",
                enum=("line", "bar", "scatter"),
                default="line",
            ),
            "title": _p(description="Chart title", required=False),
            "x_column": _p(description="Column for the x axis", required=False),
            "y_columns": _p(
                type="array",
                description="Columns to plot",
                required=False,
                items={"type": "string"},
            ),
            "max_rows": _p(type="integer", description="Maximum rows", default=5000),
        },
        "tier": 2,
        "requires_approval": True,
        "parallel_safe": False,
        "idempotent": False,
    },
}
