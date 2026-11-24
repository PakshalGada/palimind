"""Data mode upload, profile, query, chart, export and dashboard flow."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest


@pytest.fixture()
def data_client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PALIMIND_HOME", str(tmp_path / "home"))
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    csv = "region,revenue,orders\nNorth,1200,10\nSouth,800,8\nNorth,300,3\n"
    upload = client.post(
        "/api/uploads",
        json={
            "name": "sales.csv",
            "mime": "text/csv",
            "data": base64.b64encode(csv.encode()).decode(),
        },
    )
    assert upload.status_code == 200
    upload_id = upload.json()["upload"]["id"]
    return client, upload_id


def test_profile_and_query_data(data_client) -> None:
    client, upload_id = data_client
    profile = client.post("/api/data/profile", json={"upload_id": upload_id})
    assert profile.status_code == 200
    payload = profile.json()
    assert payload["rows"] == 3
    assert payload["columns"] == 3
    assert "revenue" in payload["numeric_columns"]
    assert payload["quality"]["missing_cells"] == 0
    assert payload["preview"][0]["region"] == "North"

    query = client.post(
        "/api/data/query",
        json={
            "upload_id": upload_id,
            "sql": "SELECT region, SUM(revenue) AS revenue FROM data GROUP BY region ORDER BY revenue DESC",
        },
    )
    assert query.status_code == 200
    result = query.json()
    assert result["columns"] == ["region", "revenue"]
    assert result["rows"][0] == ["North", 1500]


def test_natural_language_query_uses_local_model(data_client, monkeypatch) -> None:
    client, upload_id = data_client
    import palimind.llm.mixture_of_expert.llm as llm

    monkeypatch.setattr(
        llm,
        "llm_chat_safe",
        lambda *args, **kwargs: {
            "content": "```sql\nSELECT SUM(revenue) AS total FROM data\n```"
        },
    )
    response = client.post(
        "/api/data/query",
        json={"upload_id": upload_id, "question": "What is total revenue?"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "SELECT" in payload["sql"]
    assert payload["rows"] == [[2300]]


def test_chart_export_and_dashboard(data_client) -> None:
    client, upload_id = data_client
    chart = client.post("/api/data/chart", json={"upload_id": upload_id, "y": "revenue", "x": "region"})
    assert chart.status_code == 200
    payload = chart.json()
    assert payload["chart"]["categories"] == ["North", "South"]
    assert payload["chart"]["values"] == [1500.0, 800.0]

    export = client.post(
        "/api/data/export",
        json={"upload_id": upload_id, "cleaned": True, "format": "csv"},
    )
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    assert "region,revenue,orders" in export.text
    assert export.headers["x-palimind-filename"] == "sales-cleaned.csv"

    xlsx = client.post(
        "/api/data/export",
        json={"upload_id": upload_id, "cleaned": True, "format": "xlsx"},
    )
    assert xlsx.status_code == 200
    assert "spreadsheetml" in xlsx.headers["content-type"]
    assert xlsx.content[:2] == b"PK"

    dashboard = client.post("/api/data/dashboard", json={"upload_id": upload_id, "title": "Sales"})
    assert dashboard.status_code == 200
    result = dashboard.json()
    assert result["title"] == "Sales dashboard"
    assert "<html" in result["html"]
    assert "revenue" in result["html"]


def test_data_mode_rejects_non_tabular_upload(data_client) -> None:
    client, _upload_id = data_client
    upload = client.post(
        "/api/uploads",
        json={
            "name": "notes.txt",
            "mime": "text/plain",
            "data": base64.b64encode(b"hello").decode(),
        },
    )
    text_id = upload.json()["upload"]["id"]
    response = client.post("/api/data/profile", json={"upload_id": text_id})
    assert response.status_code == 400
