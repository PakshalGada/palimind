"""Data mode: profile uploaded tables, query them, chart, clean and export."""

from __future__ import annotations

import asyncio
import html
import io
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from palimind.chat_audit import append_chat_audit

router = APIRouter(prefix="/api/data", tags=["data"])

_TABLE_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".json", ".jsonl", ".ndjson"}
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


def _meta(upload_id: str) -> dict[str, Any]:
    from palimind.uploads import get_upload, uploads_dir

    meta = get_upload(upload_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Uploaded file not found")
    path = Path(str(meta.get("path") or "")).resolve()
    root = uploads_dir().resolve()
    if root != path and root not in path.parents:
        raise HTTPException(status_code=403, detail="Upload path is outside the uploads folder")
    if path.suffix.lower() not in _TABLE_SUFFIXES:
        raise HTTPException(status_code=400, detail="Data mode supports CSV, TSV, XLSX and JSON")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Uploaded file is missing")
    return {**meta, "path": str(path)}


def _load_frame(path: Path):
    import pandas as pd

    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t")
    if suffix in {".jsonl", ".ndjson"}:
        return pd.read_json(path, lines=True)
    if suffix == ".json":
        try:
            return pd.read_json(path)
        except ValueError:
            return pd.read_json(path, lines=True)
    return pd.read_csv(path)


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (value != value):  # NaN
            return None
        return value
    return str(value)


def _rows(df) -> list[dict[str, Any]]:
    import pandas as pd

    safe = df.astype(object).where(pd.notna(df), None)
    return [{str(key): _jsonable(value) for key, value in row.items()} for row in safe.to_dict(orient="records")]


def _profile(upload_id: str) -> dict[str, Any]:
    meta = _meta(upload_id)
    df = _load_frame(Path(meta["path"]))
    if df.empty and len(df.columns) == 0:
        raise HTTPException(status_code=400, detail="The file has no tabular data")
    import pandas as pd

    columns = []
    for name in df.columns:
        series = df[name]
        numeric = pd.api.types.is_numeric_dtype(series)
        entry: dict[str, Any] = {
            "name": str(name),
            "dtype": str(series.dtype),
            "non_null": int(series.notna().sum()),
            "missing": int(series.isna().sum()),
            "unique": int(series.nunique(dropna=True)),
            "sample": _jsonable(series.dropna().iloc[0]) if series.notna().any() else None,
        }
        if numeric:
            entry.update(
                {
                    "min": _jsonable(series.min()),
                    "max": _jsonable(series.max()),
                    "mean": _jsonable(round(float(series.mean()), 4)) if series.notna().any() else None,
                }
            )
        columns.append(entry)

    numeric = [c["name"] for c in columns if "mean" in c]
    categorical = [c["name"] for c in columns if c["name"] not in numeric][:6]
    suggestions = []
    if numeric:
        suggestions.append(f"What is the trend in {numeric[0]}?")
        suggestions.append(f"Which {categorical[0] if categorical else 'category'} has the highest {numeric[0]}?")
    if len(numeric) > 1:
        suggestions.append(f"Compare {numeric[0]} and {numeric[1]}.")
    suggestions.append("Show the rows with missing values.")
    return {
        "upload": {"id": meta["id"], "name": meta["name"], "size": meta["size"], "mime": meta.get("mime")},
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
        "numeric_columns": numeric,
        "categorical_columns": categorical,
        "column_profile": columns,
        "preview": _rows(df.head(25)),
        "quality": {
            "duplicate_rows": int(df.duplicated().sum()),
            "missing_cells": int(df.isna().sum().sum()),
            "total_cells": int(df.shape[0] * df.shape[1]),
        },
        "suggested_questions": suggestions[:4],
    }


def _clean_sql(sql: str) -> str:
    text = re.sub(r"^```(?:sql)?\s*|\s*```$", "", str(sql or "").strip(), flags=re.I | re.S).strip()
    text = text.rstrip(";")
    lowered = text.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise HTTPException(status_code=400, detail="Only SELECT or WITH queries are allowed")
    if ";" in text:
        raise HTTPException(status_code=400, detail="Only one SQL statement is allowed")
    for word in _FORBIDDEN_SQL:
        if word in lowered.split():
            raise HTTPException(status_code=400, detail=f"{word.upper()} is not allowed in a read-only query")
    return text


def _query_frame(df, sql: str, limit: int = 200) -> dict[str, Any]:
    import duckdb

    statement = _clean_sql(sql)
    conn = duckdb.connect(":memory:")
    try:
        conn.register("data", df)
        cursor = conn.execute(statement)
        columns = [item[0] for item in (cursor.description or [])]
        rows = cursor.fetchmany(max(1, min(int(limit or 200), 2000)))
        return {
            "sql": statement,
            "columns": columns,
            "rows": [[_jsonable(value) for value in row] for row in rows],
            "row_count": len(rows),
        }
    finally:
        conn.close()


def _sql_for_question(question: str, df, config: dict[str, Any]) -> str:
    from palimind.llm.mixture_of_expert.llm import llm_chat_safe

    schema = "\n".join(f"- {name} ({dtype})" for name, dtype in zip(df.columns, df.dtypes.astype(str), strict=False))
    sample = df.head(3).to_json(orient="records", date_format="iso")
    prompt = (
        "Translate the question into one read-only DuckDB SELECT query. The table is named data. "
        "Return only SQL, no commentary, no fences.\n\n"
        f"Columns:\n{schema}\n\nSample rows:\n{sample}\n\nQuestion: {question}"
    )
    model = str(config.get("chat_model") or "llama3")
    url = str(config.get("ollama_base_url") or "http://localhost:11434")
    result = llm_chat_safe(
        [
            {"role": "system", "content": "You write precise DuckDB SQL. Return only one SELECT statement."},
            {"role": "user", "content": prompt},
        ],
        model,
        url,
        error_prefix="[data sql error",
    )
    return str(result.get("content") or "").strip()


def _chart_payload(df, body: dict[str, Any]) -> dict[str, Any]:
    import pandas as pd

    kind = str(body.get("chart_type") or body.get("kind") or "bar").lower()
    if kind not in {"bar", "line", "area", "pie", "donut"}:
        kind = "bar"
    x = str(body.get("x") or "").strip()
    y = str(body.get("y") or "").strip()
    if x and x in df.columns:
        x_series = df[x]
    else:
        x_series = pd.Series(range(1, len(df) + 1), name="Row")
        x = "Row"
    if not y or y not in df.columns:
        numeric = [name for name in df.columns if pd.api.types.is_numeric_dtype(df[name]) and name != x]
        if not numeric:
            raise HTTPException(status_code=400, detail="No numeric column is available to chart")
        y = numeric[0]
    source = pd.DataFrame({"x": x_series, "y": pd.to_numeric(df[y], errors="coerce")}).dropna()
    source = source.groupby("x", dropna=False)["y"].sum().reset_index().head(20)
    return {
        "chart": {
            "kind": kind,
            "title": f"{y} by {x}",
            "unit": "",
            "categories": [str(value) for value in source["x"].tolist()],
            "values": [float(value) for value in source["y"].tolist()],
            "series_name": y,
        },
        "x": x,
        "y": y,
        "rows": _rows(source),
    }


def _dashboard(title: str, profile: dict[str, Any], charts: list[dict[str, Any]]) -> str:
    cards = "".join(
        f"<div class='kpi'><strong>{html.escape(str(item['name']))}</strong>"
        f"<span>{html.escape(str(item.get('dtype') or ''))} · {item.get('unique', 0)} unique</span></div>"
        for item in profile["column_profile"][:6]
    )
    chart_html = []
    for index, chart in enumerate(charts):
        values = chart["chart"]["values"]
        categories = chart["chart"]["categories"]
        maximum = max(values) if values else 1
        bars = "".join(
            f"<div class='bar-row'><span>{html.escape(str(cat))}</span>"
            f"<i style='width:{max(2, (value / maximum) * 100):.1f}%'></i>"
            f"<b>{value:g}</b></div>"
            for cat, value in zip(categories, values, strict=False)
        )
        chart_html.append(
            f"<section class='chart'><h2>{html.escape(chart['chart']['title'])}</h2>{bars}</section>"
        )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
:root{{color-scheme:light}}
body{{margin:0;padding:32px;background:#f7f9fc;color:#0b1220;font:15px/1.5 system-ui,sans-serif}}
h1{{margin:0 0 4px;font-size:28px}} .meta{{color:#64748b;margin-bottom:22px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:20px}}
.kpi{{padding:14px;border:1px solid #e2e8f0;border-radius:12px;background:#fff;display:flex;flex-direction:column;gap:3px}}
.kpi span{{color:#64748b;font-size:12px}}
.chart{{padding:16px;border:1px solid #e2e8f0;border-radius:12px;background:#fff;margin-bottom:14px}}
.chart h2{{margin:0 0 12px;font-size:16px}}
.bar-row{{display:grid;grid-template-columns:120px 1fr 64px;gap:8px;align-items:center;margin:6px 0;font-size:13px}}
.bar-row span{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#334155}}
.bar-row i{{display:block;height:8px;border-radius:99px;background:#2563eb;min-width:2px}}
.bar-row b{{text-align:right;color:#0b1220}}
</style></head><body>
<h1>{html.escape(title)}</h1>
<div class="meta">{profile['rows']:,} rows · {profile['columns']} columns · {profile['quality']['missing_cells']} missing cells</div>
<div class="kpis">{cards}</div>
{''.join(chart_html)}
</body></html>"""


@router.post("/profile")
async def data_profile(req: Request):
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    upload_id = str((body or {}).get("upload_id") or "").strip()
    if not upload_id:
        raise HTTPException(status_code=400, detail="upload_id is required")
    return await asyncio.to_thread(_profile, upload_id)


@router.post("/query")
async def data_query(req: Request):
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    upload_id = str((body or {}).get("upload_id") or "").strip()
    if not upload_id:
        raise HTTPException(status_code=400, detail="upload_id is required")
    meta = _meta(upload_id)
    df = await asyncio.to_thread(_load_frame, Path(meta["path"]))
    sql = str((body or {}).get("sql") or "").strip()
    question = str((body or {}).get("question") or "").strip()
    if not sql and not question:
        raise HTTPException(status_code=400, detail="sql or question is required")
    if not sql:
        from palimind import api_server as server

        config = server._global_chat_config()
        try:
            sql = await asyncio.to_thread(_sql_for_question, question, df, config)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Could not generate SQL: {exc}") from exc
    try:
        result = await asyncio.to_thread(_query_frame, df, sql)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Query failed: {exc}") from exc
    append_chat_audit(
        "data.query",
        detail={"upload_id": upload_id, "rows": result.get("row_count", 0)},
    )
    return result


@router.post("/chart")
async def data_chart(req: Request):
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    upload_id = str((body or {}).get("upload_id") or "").strip()
    if not upload_id:
        raise HTTPException(status_code=400, detail="upload_id is required")
    meta = _meta(upload_id)
    df = await asyncio.to_thread(_load_frame, Path(meta["path"]))
    sql = str((body or {}).get("sql") or "").strip()
    if sql:
        result = await asyncio.to_thread(_query_frame, df, sql, 2000)
        import pandas as pd

        df = pd.DataFrame(result["rows"], columns=result["columns"])
    return await asyncio.to_thread(_chart_payload, df, body)


@router.post("/export")
async def data_export(req: Request):
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    upload_id = str((body or {}).get("upload_id") or "").strip()
    if not upload_id:
        raise HTTPException(status_code=400, detail="upload_id is required")
    meta = _meta(upload_id)
    df = await asyncio.to_thread(_load_frame, Path(meta["path"]))
    sql = str((body or {}).get("sql") or "").strip()
    if sql:
        result = await asyncio.to_thread(_query_frame, df, sql, 5000)
        import pandas as pd

        df = pd.DataFrame(result["rows"], columns=result["columns"])
    if bool((body or {}).get("cleaned")):
        df = df.drop_duplicates().dropna(how="all")
        for column in df.columns:
            if df[column].dtype == object:
                df[column] = df[column].map(lambda value: value.strip() if isinstance(value, str) else value)
    fmt = str((body or {}).get("format") or "csv").lower()
    if fmt not in {"csv", "xlsx"}:
        raise HTTPException(status_code=400, detail="format must be csv or xlsx")
    if fmt == "xlsx":
        buffer = io.BytesIO()
        df.to_excel(buffer, index=False)
        data = buffer.getvalue()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        name = f"{Path(meta['name']).stem}-cleaned.xlsx"
    else:
        data = df.to_csv(index=False).encode("utf-8")
        media = "text/csv"
        name = f"{Path(meta['name']).stem}-cleaned.csv"
    append_chat_audit(
        "data.export",
        detail={"upload_id": upload_id, "format": fmt, "rows": int(df.shape[0])},
    )
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Palimind-Filename": name,
            "Cache-Control": "no-store",
        },
    )


@router.post("/dashboard")
async def data_dashboard(req: Request):
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    upload_id = str((body or {}).get("upload_id") or "").strip()
    if not upload_id:
        raise HTTPException(status_code=400, detail="upload_id is required")
    meta = _meta(upload_id)
    df = await asyncio.to_thread(_load_frame, Path(meta["path"]))
    profile = await asyncio.to_thread(_profile, upload_id)
    charts: list[dict[str, Any]] = []
    for column in profile["numeric_columns"][:3]:
        try:
            charts.append(await asyncio.to_thread(_chart_payload, df, {"y": column, "chart_type": "bar"}))
        except HTTPException:
            continue
    title = str(body.get("title") or Path(meta["name"]).stem or "Data dashboard")
    append_chat_audit("data.dashboard", detail={"upload_id": upload_id, "charts": len(charts)})
    return {"title": f"{title} dashboard", "html": _dashboard(title, profile, charts)}
