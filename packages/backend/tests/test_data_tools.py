"""Round-trip tests for DuckDB, Excel and chart data tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from palimind.llm.mixture_of_expert.tools import set_tool_context


@pytest.fixture()
def workspace(tmp_path: Path):
    set_tool_context(tmp_path)
    try:
        yield tmp_path
    finally:
        set_tool_context(None)


def test_duckdb_query_over_csv(workspace: Path) -> None:
    from palimind.agents.tools.data.tool import duckdb_query

    (workspace / "sales.csv").write_text("name,amount\nwidget,12\ngadget,3\n", encoding="utf-8")
    raw = duckdb_query(
        "SELECT name, amount FROM data WHERE amount > 10 ORDER BY 1",
        source="sales.csv",
    )
    payload = json.loads(raw)
    assert payload["columns"] == ["name", "amount"]
    assert payload["rows"] == [["widget", 12]]
    assert payload["truncated"] is False


def test_duckdb_rejects_writes(workspace: Path) -> None:
    from palimind.agents.tools.data.tool import duckdb_query

    assert "only SELECT" in duckdb_query("DELETE FROM data")
    assert "multiple" in duckdb_query("SELECT 1; SELECT 2")


def test_xlsx_roundtrip(workspace: Path) -> None:
    from palimind.agents.tools.data.tool import xlsx_read, xlsx_write

    out = xlsx_write(
        "book.xlsx",
        [
            {"name": "Sales", "rows": [["name", "amount"], ["a", 10], ["b", 20]]},
            {"name": "Notes", "rows": [["hello"]]},
        ],
    )
    assert "Wrote 2 sheet(s)" in out
    payload = json.loads(xlsx_read("book.xlsx", sheet="Sales"))
    assert payload["sheet"] == "Sales"
    assert payload["sheets"] == ["Sales", "Notes"]
    assert payload["rows"][1] == ["a", 10]
    assert payload["rows"][2] == ["b", 20]


def test_chart_generate(workspace: Path) -> None:
    from palimind.agents.tools.data.tool import chart_generate

    (workspace / "series.csv").write_text("x,y\n1,2\n2,4\n3,9\n", encoding="utf-8")
    out = chart_generate(
        "series.csv",
        output="charts/line.png",
        chart_type="line",
        title="Demo",
        x_column="x",
        y_columns=["y"],
    )
    assert "Generated line chart" in out
    target = workspace / "charts" / "line.png"
    assert target.is_file()
    assert target.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_data_tools_reject_paths_outside_workspace(workspace: Path) -> None:
    from palimind.agents.tools.data.tool import chart_generate, xlsx_write

    assert "access denied" in xlsx_write("../escape.xlsx", [{"name": "S", "rows": [[1]]}])
    assert "access denied" in chart_generate("/etc/hosts", "../chart.png")


def test_data_tools_registered_with_typed_schemas() -> None:
    from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY, _register_plugin_tools

    _register_plugin_tools()
    for name in ("duckdb_query", "xlsx_read", "xlsx_write", "chart_generate"):
        assert name in TOOL_REGISTRY, name
    assert TOOL_REGISTRY["duckdb_query"]["meta"]["tier"] == 1
    assert TOOL_REGISTRY["xlsx_write"]["meta"]["tier"] == 2
    assert TOOL_REGISTRY["chart_generate"]["parameters"]["y_columns"]["type"] == "array"
    assert TOOL_REGISTRY["duckdb_query"]["parameters"]["max_rows"]["type"] == "integer"
