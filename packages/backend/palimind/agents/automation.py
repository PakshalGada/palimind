"""Loopback local-scripts API.

The listener runs only while at least one agent allows automation.  It binds
127.0.0.1, refuses an Origin header or a foreign Host before it checks the
token, and writes a short-lived token to ``<home>/automation`` with 0600 files.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MAX_BODY = 32 * 1024
MAX_PAYLOAD = 4_000
REQUESTS_PER_HOUR = 30


class AutomationError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _home() -> Path:
    from palimind.security.tokens import palimind_home

    return palimind_home()


def _now() -> float:
    return time.time()


class AutomationServer:
    def __init__(self, *, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = int(port or 0)
        self.token = secrets.token_urlsafe(32)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        if self._httpd is None:
            return ""
        host, port = self._httpd.server_address[:2]
        host_text = host.decode() if isinstance(host, bytes) else str(host)
        return f"http://{host_text}:{port}"

    def start(self) -> str:
        if self._httpd is not None:
            return self.url
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "PaliMindAutomation/1.0"

            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
                return

            def _send(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _guard(self) -> None:
                origin = self.headers.get("Origin")
                if origin:
                    raise AutomationError(403, "origin not allowed")
                host = str(self.headers.get("Host") or "")
                expected = urlparse(server.url).netloc
                if host and host != expected:
                    raise AutomationError(403, "host not allowed")
                auth = str(self.headers.get("Authorization") or "")
                if auth != f"Bearer {server.token}":
                    raise AutomationError(401, "invalid token")

            def _body(self) -> dict[str, Any]:
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    raise AutomationError(400, "invalid content length") from None
                if length > MAX_BODY:
                    raise AutomationError(413, "body too large")
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    value = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    raise AutomationError(400, "body must be JSON") from None
                return value if isinstance(value, dict) else {}

            def do_GET(self) -> None:  # noqa: N802
                try:
                    self._guard()
                    result = server.dispatch("GET", urlparse(self.path).path, {})
                    self._send(200, result)
                except AutomationError as exc:
                    self._send(exc.status, {"error": str(exc)})
                except Exception as exc:  # noqa: BLE001
                    self._send(500, {"error": str(exc)})

            def do_POST(self) -> None:  # noqa: N802
                try:
                    self._guard()
                    result = server.dispatch("POST", urlparse(self.path).path, self._body())
                    self._send(202 if result.pop("_accepted", False) else 200, result)
                except AutomationError as exc:
                    self._send(exc.status, {"error": str(exc)})
                except Exception as exc:  # noqa: BLE001
                    self._send(500, {"error": str(exc)})

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = int(self._httpd.server_address[1])
        self._write_files()
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="palimind-automation", daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        self._httpd = None
        self._thread = None
        folder = _home() / "automation"
        for name in ("url", "token", "headers"):
            try:
                (folder / name).unlink()
            except OSError:
                pass

    def _write_files(self) -> None:
        folder = _home() / "automation"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(folder, 0o700)
        except OSError:
            pass
        values = {
            "url": self.url,
            "token": self.token,
            "headers": f"Authorization: Bearer {self.token}",
        }
        for name, value in values.items():
            path = folder / name
            path.write_text(value, "utf-8")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass

    def _agent(self, agent_id: str) -> Any:
        from palimind.agents.registry import get_registry

        defn = get_registry().get_by_id(agent_id)
        if defn is None:
            raise AutomationError(404, "agent not found")
        if not bool(getattr(defn, "allow_automation", False)):
            raise AutomationError(403, "agent does not allow local scripts")
        return defn

    def _limit(self, agent_id: str) -> None:
        now = _now()
        with self._lock:
            stamps = [t for t in self._requests.get(agent_id, []) if now - t < 3600]
            if len(stamps) >= REQUESTS_PER_HOUR:
                raise AutomationError(429, "request limit reached")
            stamps.append(now)
            self._requests[agent_id] = stamps

    def dispatch(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        parts = [part for part in path.split("/") if part]
        if parts[:2] != ["v1", "agents"]:
            raise AutomationError(404, "not found")
        if len(parts) == 2 and method == "GET":
            return self._list_agents()
        if len(parts) < 3:
            raise AutomationError(404, "not found")
        agent_id = parts[2]
        self._agent(agent_id)
        tail = parts[3:]

        if not tail and method == "GET":
            return self._list_agents()
        if tail == ["messages"] and method == "POST":
            self._limit(agent_id)
            return self._send_message(agent_id, body)
        if len(tail) == 2 and tail[0] == "deliveries" and method == "GET":
            return self._delivery(agent_id, tail[1])
        if tail == ["settings"] and method == "POST":
            return self._settings(agent_id, body)
        if tail == ["context", "clear"] and method == "POST":
            return self._clear_context(agent_id)
        if tail == ["pending"] and method == "GET":
            return self._pending(agent_id)
        if len(tail) == 3 and tail[0] == "routines" and tail[2] == "run" and method == "POST":
            self._limit(agent_id)
            return self._run_routine(agent_id, tail[1], body)
        if len(tail) == 3 and tail[0] == "approvals" and tail[2] == "respond" and method == "POST":
            return self._respond_approval(agent_id, tail[1], body)
        raise AutomationError(404, "not found")

    def _list_agents(self) -> dict[str, Any]:
        from palimind.agents import routines
        from palimind.agents.registry import get_registry

        out = []
        for defn in get_registry().all():
            if not bool(getattr(defn, "allow_automation", False)):
                continue
            out.append(
                {
                    "id": defn.id,
                    "name": defn.label,
                    "routines": [
                        {"id": r.get("id"), "name": r.get("name"), "active": bool(r.get("enabled"))}
                        for r in routines.list_routines(limit=500)
                        if str(r.get("target_id") or "") == defn.id
                    ],
                }
            )
        return {"agents": out}

    def _send_message(self, agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from palimind.agents import mailbox, queue

        text = str(body.get("text") or "").strip()
        if not text:
            raise AutomationError(400, "text is required")
        key = str(body.get("clientMessageId") or "")
        delivery = mailbox.send(
            agent_id,
            text,
            sender_kind="script",
            sender_id="local-script",
            idempotency_key=key,
        )
        item = queue.enqueue(
            "agent",
            agent_id,
            text,
            lane="chat",
            metadata={"delivery_id": delivery["id"]},
        )
        return {
            "messageId": delivery["id"],
            "deliveries": [
                {
                    "id": delivery["id"],
                    "recipientAgentId": agent_id,
                    "status": delivery["status"],
                    "position": item.get("priority"),
                }
            ],
            "_accepted": True,
        }

    def _delivery(self, agent_id: str, delivery_id: str) -> dict[str, Any]:
        from palimind.agents import mailbox

        delivery = mailbox.get_delivery(delivery_id)
        if delivery is None or str(delivery.get("target_agent_id")) != agent_id:
            raise AutomationError(404, "delivery not found")
        return {
            "id": delivery["id"],
            "status": delivery["status"],
            "answer": delivery.get("answer") or None,
            "error": delivery.get("error") or None,
        }

    def _settings(self, agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from palimind.agents.registry import get_registry

        allowed: dict[str, Any] = {}
        for key in ("provider", "model", "reasoning_effort", "provider_account_id"):
            if key in body:
                allowed[key] = body[key]
        if not allowed:
            raise AutomationError(400, "no supported setting")
        saved = get_registry().update(agent_id, allowed)
        return {
            "id": saved.id,
            "name": saved.label,
            "provider": saved.provider,
            "model": saved.model,
            "reasoningEffort": saved.reasoning_effort,
            "providerAccountId": saved.provider_account_id,
        }

    def _clear_context(self, agent_id: str) -> dict[str, Any]:
        from palimind.agents import threads

        thread = threads.ensure_chat_thread(agent_id)
        threads.reset_thread(thread["id"], reason="automation")
        return {"ok": True}

    def _pending(self, agent_id: str) -> dict[str, Any]:
        from palimind.agents import approvals

        items = [p for p in approvals.list_pending() if str(p.get("agent_id")) == agent_id]
        return {
            "prompts": [],
            "approvals": [
                {
                    "requestId": f"{item.get('agent_id')}:{item.get('run_id')}",
                    "kind": item.get("tool"),
                    "reason": item.get("reasoning") or item.get("summary") or "",
                }
                for item in items
            ],
            "browserTakeovers": [],
        }

    def _respond_approval(self, agent_id: str, request_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from palimind.agents.runtime import resolve_approval

        decision = str(body.get("decision") or "")
        if decision not in ("accept", "decline"):
            raise AutomationError(400, "decision must be accept or decline")
        run_id = request_id.split(":", 1)[1] if ":" in request_id else None
        ok = asyncio.run(resolve_approval(agent_id, decision == "accept", run_id=run_id))
        if not ok:
            raise AutomationError(409, "request expired")
        return {"ok": True}

    def _run_routine(self, agent_id: str, routine_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from palimind.agents import routines
        from palimind.jobs import enqueue

        routine = routines.get_routine(routine_id)
        if routine is None:
            raise AutomationError(404, "routine not found")
        if str(routine.get("target_id") or "") != agent_id:
            raise AutomationError(404, "routine not found")
        payload = str(body.get("payload") or "")
        if len(payload) > MAX_PAYLOAD:
            raise AutomationError(413, "payload too large")
        job = enqueue(
            "routine_run",
            routine_id,
            {"routine_id": routine_id, "payload": payload, "source": "script"},
            idempotency_key="",
        )
        return {"runId": job.get("id"), "deliveryId": None, "_accepted": True}


_server: AutomationServer | None = None
_lock = threading.Lock()


def get_server() -> AutomationServer | None:
    return _server


def start_server(*, port: int = 0) -> AutomationServer:
    global _server
    with _lock:
        if _server is None:
            _server = AutomationServer(port=port)
            _server.start()
        return _server


def stop_server() -> None:
    global _server
    with _lock:
        if _server is not None:
            _server.stop()
            _server = None
