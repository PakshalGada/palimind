"""Feeds, PDF capture and space export."""

from __future__ import annotations

import http.server
import io
import threading
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palimind import spaces
from palimind.spaces import feeds, sources


FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Example Feed</title>
  <item><title>First post</title><link>https://example.com/first</link><pubDate>Mon, 06 May 2024 10:00:00 GMT</pubDate></item>
  <item><title>Second post</title><link>https://example.com/second</link><pubDate>Tue, 07 May 2024 10:00:00 GMT</pubDate></item>
</channel></rss>
"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry><title>Entry one</title><link href="https://example.com/one"/><updated>2024-05-06T10:00:00Z</updated></entry>
</feed>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):  # noqa: N802
        if self.path == "/feed.xml":
            body = FEED.encode()
            ctype = "application/rss+xml"
        elif self.path == "/paper.pdf":
            body = b"%PDF-1.4\n1 0 obj <<>> endobj\ntrailer <<>>\n%%EOF"
            ctype = "application/pdf"
        else:
            body = b"not found"
            ctype = "text/plain"
        self.send_response(200 if self.path in ("/feed.xml", "/paper.pdf") else 404)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path: Path):
    import palimind.api_server as server

    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(server, "GLOBAL_CONFIG_PATH", tmp_path / "global.json")
    monkeypatch.setattr(server.state, "fields", [])
    monkeypatch.setattr(server.state, "active_field", None)
    monkeypatch.setattr(server.state, "active_space_id", None)
    monkeypatch.setattr("palimind.core.web_search._is_safe_url", lambda url: True)
    yield


def _space(tmp_path: Path) -> Path:
    parent = tmp_path / "vault"
    parent.mkdir()
    return Path(spaces.create_space("Feed KB", parent_dir=str(parent))["root"])


def test_parse_rss_and_atom() -> None:
    title, items = feeds.parse_feed(FEED, "https://example.com")
    assert title == "Example Feed"
    assert [item["title"] for item in items] == ["First post", "Second post"]

    title, items = feeds.parse_feed(ATOM)
    assert title == "Atom Feed"
    assert items[0]["url"] == "https://example.com/one"


def test_add_feed_creates_item_sources(tmp_path: Path, server_url: str) -> None:
    root = _space(tmp_path)
    result = feeds.add_feed(root, server_url + "/feed.xml")
    assert result["feed"]["kind"] == "feed"
    assert len(result["items"]) == 2
    assert all(item["parent_id"] == result["feed"]["id"] for item in result["items"])

    listed = sources.list_space_sources(root)
    assert listed["total"] == 3
    kinds = {item["kind"] for item in listed["sources"]}
    assert kinds == {"feed", "web"}


def test_pdf_url_is_saved_as_file_source(tmp_path: Path, server_url: str) -> None:
    root = _space(tmp_path)
    row = sources.create_web_source(root, server_url + "/paper.pdf")
    saved = sources.ingest_web_source(root, row["id"])
    assert saved["status"] == "ready", saved
    assert saved["kind"] == "file"
    assert saved["file_path"].endswith(".pdf")
    assert (root / saved["file_path"]).read_bytes().startswith(b"%PDF")


def test_space_export_and_graph_export(tmp_path: Path) -> None:
    import palimind.api_server as server

    root = _space(tmp_path)
    note = sources.create_text_source(root, "Export me.", title="Note")

    client = TestClient(server.app)
    space = spaces.find_by_root(root)
    exported = client.get(f"/api/spaces/{space['id']}/export")
    assert exported.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    names = archive.namelist()
    assert any(name.endswith(".md") for name in names)
    assert "space.json" in names
    assert (root / note["file_path"]).read_text("utf-8")

    graph_json = client.get(f"/api/spaces/{space['id']}/graph/export")
    assert graph_json.status_code == 200
    assert graph_json.headers["content-type"].startswith("application/json")

    graphml = client.get(
        f"/api/spaces/{space['id']}/graph/export", params={"format": "graphml"}
    )
    assert graphml.status_code == 200
    assert "<graphml" in graphml.text


def test_change_summary_reports_added_and_removed_lines() -> None:
    from palimind.spaces.web_source import summarise_change

    summary = summarise_change("one\ntwo\nthree", "one\nthree\nfour")
    assert "1 line added" in summary
    assert "1 line removed" in summary
    assert summarise_change("same", "same") == ""


def test_maintenance_only_picks_opted_in_due_sources(tmp_path: Path) -> None:
    from palimind.spaces import maintenance

    root = _space(tmp_path)
    record = sources.create_text_source(root, "body", title="Note")
    assert maintenance.due_sources(root) == []

    # Text sources are not crawled, but the query itself must stay valid.
    updated = sources.update_space_source(
        root, record["id"], {"refresh_interval": 3600}
    )
    assert updated["refresh_interval"] == 3600
    assert maintenance.due_sources(root) == []


def test_youtube_ids_and_transcript_parsing() -> None:
    from palimind.spaces import youtube

    assert youtube.video_id("https://www.youtube.com/watch?v=abc123DEF45") == "abc123DEF45"
    assert youtube.video_id("https://youtu.be/abc123DEF45?t=10") == "abc123DEF45"
    assert youtube.video_id("https://www.youtube.com/shorts/abc123DEF45") == "abc123DEF45"
    assert youtube.video_id("https://example.com/nope") == ""

    transcript = youtube.parse_transcript_xml(
        "<transcript><text start=\"65\" dur=\"2\">Hello &amp; welcome</text>"
        "<text start=\"3725\" dur=\"2\">Later</text></transcript>"
    )
    assert "[1:05] Hello & welcome" in transcript
    assert "[1:02:05] Later" in transcript


def test_youtube_ingest_writes_markdown(tmp_path: Path, monkeypatch) -> None:
    from palimind.spaces import youtube

    root = _space(tmp_path)
    record = sources.create_web_source(root, "https://youtu.be/abc123DEF45")
    monkeypatch.setattr(
        youtube,
        "fetch_transcript",
        lambda url: {
            "id": "abc123DEF45",
            "url": "https://www.youtube.com/watch?v=abc123DEF45",
            "title": "A talk",
            "author": "Speaker",
            "transcript": "[0:01] Hello world",
        },
    )
    saved = sources.ingest_web_source(root, record["id"])
    assert saved["status"] == "ready", saved
    assert saved["kind"] == "video"
    assert saved["site"] == "youtube.com"
    assert "Hello world" in (root / saved["file_path"]).read_text("utf-8")


def test_related_sources_use_shared_title_terms(tmp_path: Path) -> None:
    root = _space(tmp_path)
    first = sources.create_text_source(root, "one", title="Graph Theory Basics")
    second = sources.create_text_source(root, "two", title="Graph Theory Notes")
    sources.create_text_source(root, "three", title="Cooking")

    payload = sources.source_content(root, first["id"])
    related_ids = {item["id"] for item in payload["related"]}
    assert second["id"] in related_ids
    assert len(related_ids) == 1
