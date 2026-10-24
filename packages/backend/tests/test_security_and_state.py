"""Regression tests for the security, isolation and persistence fixes."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

# ── sandbox ───────────────────────────────────────────────────────────────


def test_sandbox_hides_host_files_and_blocks_outside_writes(tmp_path: Path) -> None:
    from palimind.security.sandbox import bwrap_path, run_python_isolated, run_shell_isolated

    if bwrap_path() is None:
        pytest.skip("bubblewrap is not installed")

    assert run_python_isolated("print(2 + 2)", root=tmp_path).strip() == "4"

    leak = run_python_isolated("print(open('/etc/passwd').read())", root=tmp_path)
    assert "Error" in leak
    assert "No such file" in leak

    outside = Path("/var/tmp/palimind-escape-test.txt")
    outside.unlink(missing_ok=True)
    write = run_python_isolated(f"open({str(outside)!r}, 'w').write('owned')", root=tmp_path)
    assert "Error" in write
    assert not outside.exists()

    assert "No such file" in run_shell_isolated("cat /etc/passwd", root=tmp_path)

    # With explicit write access the workspace itself is writable.
    ok = run_python_isolated(
        f"open({str(tmp_path / 'ok.txt')!r}, 'w').write('ok')",
        root=tmp_path,
        allow_write=True,
    )
    assert "Error" not in ok
    assert (tmp_path / "ok.txt").read_text() == "ok"


# ── API authentication ────────────────────────────────────────────────────


def test_auth_middleware_requires_token_and_sets_cookie(monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from palimind.security import auth as auth_mod

    monkeypatch.setattr(auth_mod, "auth_disabled", lambda: False)
    monkeypatch.setattr(auth_mod, "allow_remote", lambda: False)

    app = FastAPI()

    @app.get("/api/secret")
    async def secret() -> dict:
        return {"ok": True}

    @app.get("/ui")
    async def ui() -> dict:
        return {"ui": True}

    auth_mod.install_auth(app, token_provider=lambda: "test-token", cookie_path_prefix="/ui")
    client = TestClient(app)

    assert client.get("/api/secret").status_code == 401
    assert (
        client.get("/api/secret", headers={"Authorization": "Bearer test-token"}).status_code == 200
    )
    assert client.get("/api/secret", headers={"X-Palimind-Token": "test-token"}).status_code == 200

    ui_response = client.get("/ui")
    assert ui_response.status_code == 200
    assert "palimind_token" in ui_response.headers.get("set-cookie", "")
    # TestClient persists the cookie; the API now authenticates.
    assert client.get("/api/secret").status_code == 200


# ── per-thread tool context ───────────────────────────────────────────────


def test_tool_context_is_thread_local(tmp_path: Path) -> None:
    from palimind.llm.mixture_of_expert import tools as t

    barrier = threading.Barrier(2)
    seen: dict[str, str] = {}

    def worker(name: str) -> None:
        root = tmp_path / name
        root.mkdir()
        t.set_tool_context(root, agent_id=name, session_id=f"s-{name}")
        barrier.wait(timeout=5)
        ctx = t._get_context()
        seen[name] = f"{ctx['root']}|{ctx['agent_id']}|{ctx['session_id']}"

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("alpha", "beta")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert seen["alpha"] == f"{tmp_path / 'alpha'}|alpha|s-alpha"
    assert seen["beta"] == f"{tmp_path / 'beta'}|beta|s-beta"


# ── audit attribution ─────────────────────────────────────────────────────


def test_tool_audit_records_agent_and_session(tmp_path: Path) -> None:
    import json

    from palimind.llm.mixture_of_expert import tools as t

    (tmp_path / "a.txt").write_text("hello", "utf-8")
    t.set_tool_context(tmp_path, agent_id="agent-42", session_id="session-7")
    t.call_tool("list_files", path=".")
    lines = (tmp_path / ".palimind" / "tool_audit.jsonl").read_text().splitlines()
    record = json.loads(lines[-1])
    assert record["agent_id"] == "agent-42"
    assert record["session_id"] == "session-7"


# ── approval defaults ─────────────────────────────────────────────────────


def test_risky_tools_require_approval_by_default() -> None:
    from palimind.agents.catalog import DEFAULT_HITL_THRESHOLD, AgentDefinition

    defn = AgentDefinition.new("approval-default")
    assert defn.human_in_loop_threshold == DEFAULT_HITL_THRESHOLD

    # A legacy definition saved with the old implicit 0.0 is upgraded.
    legacy = AgentDefinition.from_dict({"name": "legacy", "human_in_loop_threshold": 0.0})
    assert legacy.human_in_loop_threshold == DEFAULT_HITL_THRESHOLD

    # Explicit opt-out is respected.
    opted_out = AgentDefinition.from_dict(
        {
            "name": "opted-out",
            "human_in_loop_threshold": 0.0,
            "approval_explicit": True,
        }
    )
    assert opted_out.human_in_loop_threshold == 0.0


# ── SQLite state stores ───────────────────────────────────────────────────


def test_agent_chat_concurrent_appends(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    from palimind.agents import chat

    agent_id = "concurrent-chat"
    threads = [
        threading.Thread(target=chat.append_chat, args=(agent_id, "user", f"m{i}"))
        for i in range(25)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    messages = chat.read_chat(agent_id)
    assert len(messages) == 25
    assert {m["content"] for m in messages} == {f"m{i}" for i in range(25)}


def test_run_history_is_bounded(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    from palimind.storage import state_store

    for i in range(8):
        state_store.append_run("a", f"r{i}", {"run_id": f"r{i}", "timestamp": i}, limit=3)
    runs = state_store.list_runs("a", limit=10)
    assert [r["run_id"] for r in runs] == ["r5", "r6", "r7"]


def test_session_concurrent_appends(tmp_path: Path) -> None:
    from palimind.memory import session_store

    sid = session_store.load_sessions(tmp_path)["active_session_id"]
    threads = [
        threading.Thread(
            target=session_store.append_message_to_session,
            args=(tmp_path, sid, "user", f"m{i}"),
        )
        for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    messages = session_store.load_session_by_id(tmp_path, sid)["messages"]
    assert len(messages) == 20


def test_run_journal_recovers_interrupted_runs(monkeypatch, tmp_path: Path) -> None:
    import palimind.agents.run_journal as journal

    monkeypatch.setattr(journal, "_journal_dir", lambda: tmp_path)
    journal.start("run-1", "agent-1", "do work")
    recovered: list[tuple] = []

    def record(*args) -> None:
        recovered.append(args)

    result = journal.recover_interrupted(record)
    assert result and result[0]["status"] == "interrupted"
    assert recovered and recovered[0][0] == "agent-1"
    # A second pass must not duplicate the recovery.
    assert journal.recover_interrupted(record) == []
